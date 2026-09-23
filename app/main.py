import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import storage, llm
from .analysis import analyze
from .parsers import FORMATS, MAX_FILE_BYTES, parse_document
from .reports import html_report, xlsx_report, docx_report

ROOT = Path(__file__).resolve().parents[1]
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")
login_attempts = defaultdict(list)
login_lock = threading.Lock()
COOKIE = "ai_nam_session"
MAX_FILES = 20
MAX_TOTAL = 100 * 1024 * 1024


@asynccontextmanager
async def lifespan(app):
    storage.init()
    yield
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="AI-NAM", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
hosts = [x.strip() for x in os.getenv("AI_NAM_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


@app.middleware("http")
async def protections(request: Request, call_next):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        origin = request.headers.get("origin")
        expected_origin = os.getenv("AI_NAM_PUBLIC_ORIGIN", str(request.base_url)).rstrip("/")
        if origin and origin.rstrip("/") != expected_origin:
            return Response("Cross-origin request rejected", status_code=403)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_TOTAL + 1024 * 1024):
            return Response(json.dumps({"detail": "Комплект превышает 100 МБ."}), status_code=413, media_type="application/json")
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def current_user(request: Request):
    user = storage.session_user(request.cookies.get(COOKIE))
    if not user:
        raise HTTPException(401, "Войдите в систему.")
    return user


def analyst(user=Depends(current_user)):
    if user["role"] not in {"admin", "analyst"}:
        raise HTTPException(403, "Для этого действия нужна роль аналитика.")
    return user


def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Для этого действия нужна роль администратора.")
    return user


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=200)


class NewUser(Credentials):
    name: str = Field(min_length=2, max_length=100)
    role: Literal["admin", "analyst", "viewer"] = "analyst"


def validate_password(password):
    if len(password) < 10:
        raise HTTPException(422, "Пароль должен содержать не менее 10 символов.")


def set_session(response, uid):
    response.set_cookie(COOKIE, storage.new_session(uid), max_age=43200, httponly=True, secure=os.getenv("AI_NAM_SECURE_COOKIES", "false").lower() == "true", samesite="strict", path="/")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


def local_setup(request):
    return request.client.host in {"127.0.0.1", "::1", "testclient"} and request.url.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}


@app.get("/api/auth/state")
def auth_state(request: Request):
    return {"setup_required": storage.user_count() == 0, "user": storage.session_user(request.cookies.get(COOKIE)), "can_setup": local_setup(request)}


@app.post("/api/auth/setup")
def setup(body: NewUser, request: Request, response: Response):
    if not local_setup(request):
        raise HTTPException(403, "Первого администратора нужно создать на компьютере сервера через localhost.")
    validate_password(body.password)
    try:
        user = storage.create_user(body.username, body.name, "admin", body.password, bootstrap=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    set_session(response, user["id"])
    storage.log(user["id"], "setup", detail="Создан первый администратор")
    return {"user": user}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    key = request.client.host
    with login_lock:
        login_attempts[key] = [t for t in login_attempts[key] if t > time.time() - 60]
        if len(login_attempts[key]) >= 10:
            raise HTTPException(429, "Слишком много попыток. Повторите через минуту.")
        login_attempts[key].append(time.time())
    user = storage.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(401, "Неверный логин или пароль.")
    set_session(response, user["id"])
    storage.log(user["id"], "login")
    return {"user": user}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    storage.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/config")
def config(user=Depends(current_user)):
    return {"ai": llm.config(probe=True), "limits": {"file_mb": 20, "total_mb": 100, "files_per_side": MAX_FILES, "pdf_pages": 300, "function_fragments": 6000}, "formats": sorted(FORMATS), "workspace": "private_by_default", "user": user}


@app.get("/api/users")
def users(user=Depends(admin)):
    with storage.connect() as con:
        return [storage.public_user(r) for r in con.execute("SELECT * FROM users ORDER BY created")]


@app.post("/api/users")
def add_user(body: NewUser, user=Depends(admin)):
    validate_password(body.password)
    try:
        created = storage.create_user(body.username, body.name, body.role, body.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    storage.log(user["id"], "user_created", created["id"], created["role"])
    return created


class UserAccess(BaseModel):
    active: bool
    role: Literal["admin", "analyst", "viewer"]


@app.patch("/api/users/{uid}")
def user_access(uid: str, body: UserAccess, user=Depends(admin)):
    if uid == user["id"]:
        raise HTTPException(400, "Собственную роль и доступ изменить нельзя.")
    with storage.connect() as con:
        cursor = con.execute("UPDATE users SET active=?,role=? WHERE id=?", (int(body.active), body.role, uid))
        if not cursor.rowcount:
            raise HTTPException(404, "Пользователь не найден.")
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    storage.log(user["id"], "user_access_changed", uid, body.role + (" active" if body.active else " disabled"))
    return {"ok": True}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=200)


@app.post("/api/auth/password")
def change_password(body: PasswordChange, response: Response, user=Depends(current_user)):
    if not storage.authenticate(user["username"], body.current_password):
        raise HTTPException(400, "Текущий пароль неверен.")
    with storage.connect() as con:
        con.execute("UPDATE users SET password=? WHERE id=?", (storage.password_hash(body.new_password), user["id"]))
        con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    set_session(response, user["id"])
    storage.log(user["id"], "password_changed")
    return {"ok": True}


@app.get("/api/audit")
def audit(user=Depends(admin)):
    with storage.connect() as con:
        return [dict(r) for r in con.execute("SELECT a.*,u.name FROM audit a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 100")]


@app.get("/api/cases")
def cases(user=Depends(current_user)):
    return storage.list_cases(user)


def require_case(cid, user=None, complete=False):
    case = storage.get_case(cid)
    if not case or (user and not storage.can_access(case, user)):
        raise HTTPException(404, "Сравнение не найдено.")
    if complete and case["status"] != "complete":
        raise HTTPException(409, "Дождитесь завершения анализа.")
    return case


@app.get("/api/cases/{cid}")
def case(cid: str, user=Depends(current_user)):
    case = require_case(cid, user)
    case["manifest"] = [{k: v for k, v in d.items() if k != "path"} for d in case["manifest"]]
    return case


def run_analysis(cid):
    try:
        case = require_case(cid)
        documents = []
        for i, entry in enumerate(case["manifest"]):
            storage.update_progress(cid, 10 + int(25 * i / len(case["manifest"])), "Читаем документ: " + entry["name"])
            doc = parse_document(Path(entry["path"]).read_bytes(), entry["name"], entry["side"], entry["id"])
            doc.source_url = entry.get("source_url", "")
            documents.append(doc)
        result = analyze(documents, lambda percent, stage: storage.update_progress(cid, percent, stage))
        if case["use_ai"]:
            storage.save_intermediate(cid, result)
            result = llm.enrich(result, lambda percent, stage: storage.update_progress(cid, percent, stage))
        storage.finish_case(cid, result)
        storage.log(case["owner_id"], "analysis_completed", cid, result["method"])
    except Exception as exc:
        logging.exception("Analysis failed: %s", cid)
        message = str(exc) if isinstance(exc, ValueError) else "Не удалось завершить обработку. Проверьте формат файлов и повторите сравнение. Подробности записаны в журнал сервера."
        storage.finish_case(cid, error=message)


def check_queue():
    with storage.connect() as con:
        running = con.execute("SELECT COUNT(*) FROM cases WHERE status='processing'").fetchone()[0]
    if running >= 4:
        raise HTTPException(429, "Сейчас обрабатываются четыре комплекта. Дождитесь завершения одного из них.")


@app.post("/api/cases")
async def create_case(title: str = Form(..., min_length=2, max_length=160), use_ai: bool = Form(False), before: list[UploadFile] = File(...), after: list[UploadFile] = File(...), user=Depends(analyst)):
    check_queue()
    if not title.strip():
        raise HTTPException(422, "Введите название сравнения.")
    if not before or not after or len(before) > MAX_FILES or len(after) > MAX_FILES:
        raise HTTPException(422, f"Загрузите от 1 до {MAX_FILES} файлов в каждый комплект.")
    uploads, total = [], 0
    for side, files in [("before", before), ("after", after)]:
        seen = set()
        for file in files:
            name = re.sub(r"[\\/\x00-\x1f]", "_", file.filename or "document")[:180]
            if Path(name).suffix.lower() not in FORMATS:
                raise HTTPException(422, f"{name}: поддерживаются DOCX, PDF, XLSX, TXT.")
            data = await file.read(MAX_FILE_BYTES + 1)
            if not data or len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"{name}: файл пуст или больше 20 МБ.")
            total += len(data)
            if total > MAX_TOTAL:
                raise HTTPException(413, "Суммарный размер файлов превышает 100 МБ.")
            import hashlib
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                raise HTTPException(422, f"{name}: один и тот же файл добавлен в комплект дважды.")
            seen.add(digest)
            uploads.append((side, name, data))
    group = storage.DATA_DIR / "uploads" / secrets.token_hex(12)
    group.mkdir(parents=True, exist_ok=True)
    manifest = []
    for side, name, data in uploads:
        did = secrets.token_hex(10)
        path = group / (did + Path(name).suffix.lower())
        path.write_bytes(data)
        manifest.append({"id": did, "name": name, "side": side, "size": len(data), "path": str(path)})
    cid = storage.create_case(title.strip(), user["id"], manifest, use_ai)
    storage.log(user["id"], "analysis_created", cid, f"{len(manifest)} files")
    executor.submit(run_analysis, cid)
    return {"id": cid}


class DemoRequest(BaseModel):
    use_ai: bool = False


@app.post("/api/demo")
def demo(body: DemoRequest, user=Depends(analyst)):
    check_queue()
    manifest = []
    for version, side, source in [("8", "before", "1X2tNOF9_ZF2ms0Fnx1mWrUaAoMLHabTu"), ("9", "after", "1FUh7Ld40xk-gwXMdj5-_3-p-cYeIl2hu")]:
        path = ROOT / "samples" / f"audit-v{version}.docx"
        if not path.exists():
            raise HTTPException(404, "Примеры отсутствуют. Загрузите свои файлы.")
        manifest.append({"id": secrets.token_hex(10), "name": f"Положение о внутреннем аудите · редакция {version}.docx", "side": side, "size": path.stat().st_size, "path": str(path), "source_url": f"https://docs.google.com/document/d/{source}/edit"})
    cid = storage.create_case("Внутренний аудит · редакции 8 → 9", user["id"], manifest, body.use_ai)
    storage.log(user["id"], "demo_created", cid)
    executor.submit(run_analysis, cid)
    return {"id": cid}


class Review(BaseModel):
    status: Literal["pending", "confirmed", "rejected"]
    comment: str = Field(default="", max_length=3000)


class Sharing(BaseModel):
    shared: bool


@app.patch("/api/cases/{cid}/sharing")
def sharing(cid: str, body: Sharing, user=Depends(analyst)):
    case = require_case(cid, user)
    if user["role"] != "admin" and case["owner_id"] != user["id"]:
        raise HTTPException(403, "Доступом управляет автор или администратор.")
    with storage.connect() as con:
        con.execute("UPDATE cases SET shared=? WHERE id=?", (int(body.shared), cid))
    storage.log(user["id"], "sharing_changed", cid, "team" if body.shared else "private")
    return {"shared": body.shared}


@app.patch("/api/cases/{cid}/findings/{fid}")
def review(cid: str, fid: str, body: Review, user=Depends(analyst)):
    require_case(cid, user, complete=True)
    try:
        return storage.review(cid, fid, body.status, body.comment, user)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/cases/{cid}/documents/{did}/download")
def download(cid: str, did: str, user=Depends(current_user)):
    case = require_case(cid, user)
    entry = next((d for d in case["manifest"] if d["id"] == did), None)
    if not entry or not Path(entry["path"]).is_file():
        raise HTTPException(404, "Файл не найден.")
    storage.log(user["id"], "document_downloaded", cid, did)
    return FileResponse(entry["path"], filename=entry["name"], media_type="application/octet-stream")


@app.get("/api/cases/{cid}/export/{format}")
def export(cid: str, format: Literal["html", "xlsx", "docx", "json"], user=Depends(current_user)):
    case = require_case(cid, user, complete=True)
    storage.log(user["id"], "report_exported", cid, format)
    headers = {"Content-Disposition": f'attachment; filename="AI-NAM-report.{format}"'}
    if format == "html":
        return HTMLResponse(html_report(case), headers=headers)
    if format == "xlsx":
        return Response(xlsx_report(case), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)
    if format == "docx":
        return Response(docx_report(case), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers=headers)
    payload = {k: case[k] for k in ["id", "title", "created", "owner_name", "result"]}
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json", headers=headers)


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html", headers={"Cache-Control": "no-cache"})
