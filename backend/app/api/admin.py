from __future__ import annotations

import platform
import secrets
import shutil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.security import hash_password
from ..db import get_db
from ..docgen.report import soffice_available
from ..models import AnalysisRun, AuditLog, Document, GeneratedFile, Project, Role, User
from ..parsing.ocr import available_langs, tesseract_available
from ..services.audit import log_action
from ..services.llm import LLMClient, LLMError
from ..services.settings_store import get_setting, put_setting, reset_setting
from .auth import user_out
from .deps import client_ip, current_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])

LLM_PRESETS = [
    {"id": "ollama", "title": "Ollama (локально)", "base_url": "http://localhost:11434/v1",
     "model": "qwen2.5:7b-instruct", "vision_model": "qwen2.5vl:7b", "embed_model": "bge-m3",
     "hint": "ollama pull qwen2.5:7b-instruct && ollama pull bge-m3"},
    {"id": "ollama-docker", "title": "Ollama в docker compose", "base_url": "http://ollama:11434/v1",
     "model": "qwen2.5:7b-instruct", "vision_model": "", "embed_model": "bge-m3",
     "hint": "docker compose --profile ollama up -d"},
    {"id": "lmstudio", "title": "LM Studio", "base_url": "http://localhost:1234/v1", "model": "",
     "vision_model": "", "embed_model": "", "hint": "Включите Local Server в LM Studio"},
    {"id": "vllm", "title": "vLLM", "base_url": "http://localhost:8001/v1", "model": "Qwen/Qwen2.5-7B-Instruct",
     "vision_model": "", "embed_model": "", "hint": "vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001"},
    {"id": "llamacpp", "title": "llama.cpp server", "base_url": "http://localhost:8080/v1", "model": "local",
     "vision_model": "", "embed_model": "", "hint": "llama-server -m model.gguf --port 8080"},
    {"id": "openai", "title": "OpenAI-совместимое облако", "base_url": "https://api.openai.com/v1",
     "model": "gpt-4o-mini", "vision_model": "gpt-4o-mini", "embed_model": "text-embedding-3-small",
     "hint": "Нужен API-ключ; данные уходят во внешний сервис"},
]


class UserIn(BaseModel):
    email: str
    full_name: str = ""
    role: str = Role.ANALYST
    password: str | None = None


class UserPatch(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class SettingsIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


def _mask(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(cfg)
    key = out.get("api_key") or ""
    out["api_key"] = (key[:3] + "…" + key[-3:]) if len(key) > 8 else ("•••" if key else "")
    out["api_key_set"] = bool(key)
    return out


@router.get("/stats")
def stats(db: Session = Depends(get_db), admin: User = Depends(current_admin)) -> dict[str, Any]:
    users_by_role = dict(db.query(User.role, func.count(User.id)).group_by(User.role).all())
    runs = dict(db.query(AnalysisRun.status, func.count(AnalysisRun.id)).group_by(AnalysisRun.status).all())
    llm_cfg = get_setting(db, "llm")
    recent = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(8).all()
    return {
        "users": db.query(func.count(User.id)).scalar(),
        "users_by_role": users_by_role,
        "active_users": db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar(),
        "projects": db.query(func.count(Project.id)).scalar(),
        "documents": db.query(func.count(Document.id)).scalar(),
        "documents_error": db.query(func.count(Document.id)).filter(Document.status == "error").scalar(),
        "runs": runs,
        "files": db.query(func.count(GeneratedFile.id)).scalar(),
        "llm": {"provider": llm_cfg["provider"], "model": llm_cfg["model"], "enabled": LLMClient(llm_cfg).enabled},
        "ocr": tesseract_available(),
        "pdf": soffice_available(),
        "recent": [_audit_out(a) for a in recent],
    }


# ------------------------------------------------------------------ пользователи


@router.get("/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    return [user_out(u) for u in db.query(User).order_by(User.id).all()]


@router.post("/users")
def create_user(data: UserIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    email = data.email.strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Некорректный e-mail")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Пользователь с таким e-mail уже существует")
    if data.role not in Role.ALL:
        raise HTTPException(400, "Неизвестная роль")
    password = data.password or secrets.token_urlsafe(8)
    if len(password) < 8:
        raise HTTPException(400, "Пароль должен быть не короче 8 символов")
    u = User(email=email, full_name=data.full_name.strip(), role=data.role, password_hash=hash_password(password),
             must_change_password=not data.password)
    db.add(u)
    db.commit()
    log_action(db, admin, "user_created", "user", u.id, {"email": email, "role": data.role}, client_ip(request))
    return {**user_out(u), "temporary_password": None if data.password else password}


@router.patch("/users/{user_id}")
def patch_user(user_id: int, data: UserPatch, request: Request, db: Session = Depends(get_db),
               admin: User = Depends(current_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id and (data.is_active is False or (data.role and data.role != Role.ADMIN)):
        raise HTTPException(400, "Нельзя заблокировать себя или снять с себя роль администратора")
    changes: dict[str, Any] = {}
    if data.full_name is not None:
        u.full_name = data.full_name.strip()
        changes["full_name"] = u.full_name
    if data.role is not None:
        if data.role not in Role.ALL:
            raise HTTPException(400, "Неизвестная роль")
        if u.role == Role.ADMIN and data.role != Role.ADMIN and \
                db.query(User).filter(User.role == Role.ADMIN, User.is_active.is_(True)).count() <= 1:
            raise HTTPException(400, "В системе должен остаться хотя бы один администратор")
        u.role = data.role
        changes["role"] = data.role
    if data.is_active is not None:
        u.is_active = data.is_active
        changes["is_active"] = data.is_active
    db.commit()
    log_action(db, admin, "user_updated", "user", u.id, changes, client_ip(request))
    return user_out(u)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    password = secrets.token_urlsafe(8)
    u.password_hash = hash_password(password)
    u.must_change_password = True
    db.commit()
    log_action(db, admin, "password_reset", "user", u.id, {}, client_ip(request))
    return {"temporary_password": password}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя удалить собственную учётную запись")
    email = u.email
    db.delete(u)
    db.commit()
    log_action(db, admin, "user_deleted", "user", user_id, {"email": email}, client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ настройки


@router.get("/settings/{key}")
def read_settings(key: str, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    if key not in ("llm", "analysis", "org"):
        raise HTTPException(404, "Неизвестный раздел настроек")
    value = get_setting(db, key)
    return _mask(value) if key == "llm" else value


@router.put("/settings/{key}")
def write_settings(key: str, data: SettingsIn, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(current_admin)):
    if key not in ("llm", "analysis", "org"):
        raise HTTPException(404, "Неизвестный раздел настроек")
    values = dict(data.values)
    if key == "llm":
        if "api_key" in values and ("…" in str(values["api_key"]) or values["api_key"] == "•••"):
            values.pop("api_key")  # замаскированное значение не перезаписываем
        if values.get("provider") not in (None, "none", "openai"):
            raise HTTPException(400, "provider: none или openai (OpenAI-совместимый API)")
    if key == "analysis":
        for k in ("match_high", "match_low", "duplicate", "unit_name"):
            if k in values and not (0 < float(values[k]) < 1):
                raise HTTPException(400, f"{k}: значение должно быть от 0 до 1")
        if float(values.get("match_low", 0)) >= float(values.get("match_high", 1)):
            raise HTTPException(400, "Нижний порог должен быть меньше верхнего")
    result = put_setting(db, key, values)
    log_action(db, admin, "settings_updated", "settings", key,
               {k: ("***" if k == "api_key" else v) for k, v in values.items()}, client_ip(request))
    return _mask(result) if key == "llm" else result


@router.post("/settings/{key}/reset")
def reset_settings(key: str, request: Request, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    if key not in ("llm", "analysis", "org"):
        raise HTTPException(404, "Неизвестный раздел настроек")
    result = reset_setting(db, key)
    log_action(db, admin, "settings_reset", "settings", key, {}, client_ip(request))
    return _mask(result) if key == "llm" else result


@router.get("/llm/presets")
def llm_presets(admin: User = Depends(current_admin)):
    return LLM_PRESETS


@router.post("/llm/test")
def llm_test(data: SettingsIn, db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    """Проверяет подключение с переданными (ещё не сохранёнными) параметрами."""
    cfg = get_setting(db, "llm")
    values = {k: v for k, v in data.values.items() if not (k == "api_key" and ("…" in str(v) or v == "•••"))}
    cfg.update(values)
    client = LLMClient(cfg)
    result = client.health()
    if cfg.get("provider") != "none":
        try:
            result["models"] = client.list_models()[:50]
        except LLMError as exc:
            result["models_error"] = str(exc)
    return result


# ------------------------------------------------------------------ журнал и система


def _audit_out(a: AuditLog) -> dict[str, Any]:
    return {"id": a.id, "user": a.user_email, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
            "details": a.details, "ip": a.ip, "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/audit")
def audit(limit: int = 200, action: str | None = None, user: str | None = None, db: Session = Depends(get_db),
          admin: User = Depends(current_admin)):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    if user:
        q = q.filter(AuditLog.user_email.ilike(f"%{user}%"))
    return [_audit_out(a) for a in q.order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()]


@router.get("/system")
def system(db: Session = Depends(get_db), admin: User = Depends(current_admin)):
    s = get_settings()
    disk = shutil.disk_usage(s.data_dir)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "database": s.db_url.split("://")[0],
        "data_dir": str(s.data_dir),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "ocr": {"available": tesseract_available(), "langs": available_langs() if tesseract_available() else ""},
        "pdf_export": soffice_available(),
        "frontend_built": s.frontend_dist.exists(),
    }
