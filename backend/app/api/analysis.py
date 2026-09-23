from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..analysis.conclusion import build_conclusion
from ..db import get_db
from ..docgen.report import conclusion_docx, docx_to_pdf, function_map_xlsx
from ..models import AnalysisRun, ChatMessage, FindingReview, GeneratedFile, User
from ..services.agent import get_llm, reviews_map, start_analysis
from ..services.audit import log_action
from ..services.chat import answer
from ..services.settings_store import get_setting
from .deps import client_ip, current_user, get_project_or_404, require_editor

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalysisIn(BaseModel):
    use_llm: bool = True
    use_edited_structure: bool = True
    thresholds: dict[str, float] = {}


class ReviewIn(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected|pending)$")
    comment: str = ""


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def run_brief(run: AnalysisRun) -> dict[str, Any]:
    s = (run.result or {}).get("summary", {})
    return {"id": run.id, "project_id": run.project_id, "status": run.status, "progress": run.progress,
            "current_step": run.current_step, "llm_model": run.llm_model, "error": run.error,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "summary": s, "trace": run.trace or []}


def _run_or_404(db: Session, run_id: int) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if not run:
        raise HTTPException(404, "Запуск анализа не найден")
    return run


@router.post("/projects/{project_id}/analysis")
def run_analysis(project_id: int, data: AnalysisIn, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_editor)) -> dict[str, Any]:
    p = get_project_or_404(project_id, db)
    active = db.query(AnalysisRun).filter(AnalysisRun.project_id == p.id,
                                          AnalysisRun.status.in_(("pending", "running"))).first()
    if active:
        return run_brief(active)
    run = start_analysis(db, p, user.id, data.model_dump())
    log_action(db, user, "analysis_started", "project", p.id, {"run_id": run.id}, client_ip(request))
    return run_brief(run)


@router.get("/projects/{project_id}/analysis")
def list_runs(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project_or_404(project_id, db)
    runs = db.query(AnalysisRun).filter_by(project_id=project_id).order_by(AnalysisRun.id.desc()).limit(20).all()
    return [{k: v for k, v in run_brief(r).items() if k != "trace"} for r in runs]


@router.get("/analysis/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    run = _run_or_404(db, run_id)
    out = run_brief(run)
    if run.result:
        reviews = {r.finding_id: r for r in db.query(FindingReview).filter_by(run_id=run.id).all()}
        result = dict(run.result)
        result["findings"] = [
            {**f, "review": {"status": reviews[f["id"]].status, "comment": reviews[f["id"]].comment,
                             "reviewer": (reviews[f["id"]].reviewer.full_name or reviews[f["id"]].reviewer.email)
                             if reviews[f["id"]].reviewer else "",
                             "updated_at": reviews[f["id"]].updated_at.isoformat() if reviews[f["id"]].updated_at else None}
             if f["id"] in reviews else {"status": "pending", "comment": ""}}
            for f in result.get("findings", [])
        ]
        out["result"] = result
    return out


@router.get("/analysis/{run_id}/status")
def run_status(run_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return run_brief(_run_or_404(db, run_id))


@router.put("/analysis/{run_id}/findings/{finding_id}/review")
def review_finding(run_id: int, finding_id: str, data: ReviewIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_editor)) -> dict[str, Any]:
    run = _run_or_404(db, run_id)
    if not any(f["id"] == finding_id for f in (run.result or {}).get("findings", [])):
        raise HTTPException(404, "Вывод не найден")
    r = db.query(FindingReview).filter_by(run_id=run_id, finding_id=finding_id).first()
    if not r:
        r = FindingReview(run_id=run_id, finding_id=finding_id)
        db.add(r)
    r.status, r.comment, r.reviewer_id = data.status, data.comment, user.id
    db.commit()
    log_action(db, user, "finding_reviewed", "analysis", run_id, {"finding": finding_id, "status": data.status},
               client_ip(request))
    return {"finding_id": finding_id, "status": r.status, "comment": r.comment,
            "reviewer": user.full_name or user.email}


def _conclusion(db: Session, run: AnalysisRun, lang: str) -> dict[str, Any]:
    if not run.result:
        raise HTTPException(409, "Анализ ещё не завершён")
    reviews = reviews_map(db, run.id)
    base = run.result.get("conclusion") or {}
    project = get_project_or_404(run.project_id, db)
    llm = get_llm(db) if run.llm_model else None
    if lang == "ru" and not reviews and base:
        return base
    concl = build_conclusion(run.result, run.result.get("documents", []), lang, reviews, llm, project.name)
    if base and lang == "ru":
        # сохраняем резюме модели из исходного запуска, пересчитывая только статусы проверки
        for sec, old in zip(concl["sections"], base.get("sections", [])):
            if sec["id"] == "summary" and old.get("method") and "ИИ-модель" in old.get("method", ""):
                sec["paragraphs"][0] = old["paragraphs"][0]
                sec["method"] = old["method"]
    return concl


@router.get("/analysis/{run_id}/conclusion")
def get_conclusion(run_id: int, lang: str = "ru", db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _conclusion(db, _run_or_404(db, run_id), "kz" if lang == "kz" else "ru")


def _attachment(data: bytes, filename: str, media: str) -> Response:
    return Response(data, media_type=media,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.get("/analysis/{run_id}/export/{kind}")
def export(run_id: int, kind: str, lang: str = "ru", db: Session = Depends(get_db),
           user: User = Depends(current_user)) -> Response:
    run = _run_or_404(db, run_id)
    if not run.result:
        raise HTTPException(409, "Анализ ещё не завершён")
    lang = "kz" if lang == "kz" else "ru"
    suffix = "KZ" if lang == "kz" else "RU"
    if kind in ("conclusion.docx", "conclusion.pdf"):
        concl = _conclusion(db, run, lang)
        data = conclusion_docx(concl, run.result, lang, get_setting(db, "org"))
        if kind.endswith(".pdf"):
            pdf = docx_to_pdf(data)
            if pdf is None:
                raise HTTPException(501, "Экспорт в PDF требует LibreOffice (есть в Docker-образе). Скачайте DOCX.")
            return _attachment(pdf, f"Заключение_{run.id}_{suffix}.pdf", "application/pdf")
        return _attachment(data, f"Заключение_{run.id}_{suffix}.docx",
                           "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if kind == "mapping.xlsx":
        return _attachment(function_map_xlsx(run.result, lang), f"Сопоставление_функций_{run.id}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if kind == "result.json":
        reviews = reviews_map(db, run.id)
        payload = dict(run.result)
        payload["reviews"] = reviews
        return _attachment(json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"),
                           f"Результаты_анализа_{run.id}.json", "application/json")
    raise HTTPException(404, "Неизвестный формат")


# ------------------------------------------------------------------ диалог с агентом


@router.get("/projects/{project_id}/chat")
def chat_history(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project_or_404(project_id, db)
    msgs = db.query(ChatMessage).filter_by(project_id=project_id).order_by(ChatMessage.id).all()
    return [{"id": m.id, "role": m.role, "content": m.content, "sources": m.sources, "meta": m.meta,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs]


@router.post("/projects/{project_id}/chat")
def chat(project_id: int, data: ChatIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project_or_404(project_id, db)
    db.add(ChatMessage(project_id=project_id, user_id=user.id, role="user", content=data.message))
    db.commit()
    res = answer(db, project_id, data.message, get_llm(db))
    msg = ChatMessage(project_id=project_id, user_id=user.id, role="assistant", content=res["content"],
                      sources=res["sources"], meta={"mode": res["mode"], "model": res.get("model", "")})
    db.add(msg)
    db.commit()
    return {"id": msg.id, "role": "assistant", "content": msg.content, "sources": msg.sources, "meta": msg.meta}


@router.delete("/projects/{project_id}/chat")
def chat_clear(project_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    db.query(ChatMessage).filter_by(project_id=project_id).delete()
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ сформированные файлы


@router.get("/projects/{project_id}/files")
def list_files(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    files = db.query(GeneratedFile).filter_by(project_id=project_id).order_by(GeneratedFile.id.desc()).all()
    return [{"id": f.id, "kind": f.kind, "title": f.title, "filename": f.filename, "lang": f.lang,
             "created_at": f.created_at.isoformat() if f.created_at else None,
             "size": Path(f.path).stat().st_size if Path(f.path).exists() else 0} for f in files]


@router.get("/files/{file_id}")
def download_file(file_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = db.get(GeneratedFile, file_id)
    if not f or not Path(f.path).exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(f.path, filename=f.filename)
