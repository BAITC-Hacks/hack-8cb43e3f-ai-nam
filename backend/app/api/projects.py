from __future__ import annotations

import base64
import io
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analysis.compare import Comparator
from ..analysis.structure import unit_type_of
from ..analysis.text import Similarity
from ..config import get_settings
from ..db import get_db
from ..docgen.package import blocks_to_html, build_package, regulation_blocks
from ..models import AnalysisRun, Document, GeneratedFile, Project, Role, Structure, User
from ..orgchart.extract import extract_orgchart_from_file, extract_with_vision
from ..orgchart.render import render_chart
from ..services.agent import doc_payload, get_llm, structure_for_side
from ..services.audit import log_action
from ..services.documents import SIDES, doc_brief, parse_in_background, store_upload
from ..services.llm import LLMError
from ..services.settings_store import get_setting
from .deps import client_ip, current_user, get_project_or_404, require_editor

router = APIRouter(prefix="/api", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class DocPatch(BaseModel):
    side: str


class StructureIn(BaseModel):
    units: list[dict[str, Any]]


class PackageIn(BaseModel):
    langs: list[str] = ["ru"]
    unit_ids: list[str] | None = None
    include_sources: bool = True
    translate_kz: bool = True


class PreviewIn(BaseModel):
    unit_id: str
    lang: str = "ru"
    include_sources: bool = True


def project_out(db: Session, p: Project) -> dict[str, Any]:
    counts = dict(db.query(Document.side, func.count(Document.id)).filter(Document.project_id == p.id)
                  .group_by(Document.side).all())
    run = db.query(AnalysisRun).filter_by(project_id=p.id).order_by(AnalysisRun.id.desc()).first()
    last = None
    if run:
        s = (run.result or {}).get("summary", {})
        last = {"id": run.id, "status": run.status, "progress": run.progress,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "lost": s.get("lost"), "duplicates": s.get("duplicates"), "conflicts": s.get("conflicts"),
                "findings": s.get("findings"), "units_by_status": s.get("units_by_status")}
    return {
        "id": p.id, "name": p.name, "description": p.description, "status": p.status, "is_demo": p.is_demo,
        "owner": p.owner.full_name or p.owner.email if p.owner else "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "documents": {s: counts.get(s, 0) for s in SIDES}, "last_run": last,
    }


# ------------------------------------------------------------------ проекты


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return [project_out(db, p) for p in db.query(Project).order_by(Project.updated_at.desc()).all()]


@router.post("/projects")
def create_project(data: ProjectIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_editor)) -> dict[str, Any]:
    p = Project(name=data.name.strip(), description=data.description.strip(), owner_id=user.id)
    db.add(p)
    db.commit()
    log_action(db, user, "project_created", "project", p.id, {"name": p.name}, client_ip(request))
    return project_out(db, p)


@router.post("/projects/demo")
def create_demo(request: Request, db: Session = Depends(get_db), user: User = Depends(require_editor)) -> dict[str, Any]:
    from ..services.demo import create_demo_project

    p = create_demo_project(db, user.id)
    log_action(db, user, "demo_created", "project", p.id, {}, client_ip(request))
    return project_out(db, p)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    return project_out(db, get_project_or_404(project_id, db))


@router.patch("/projects/{project_id}")
def patch_project(project_id: int, data: ProjectPatch, db: Session = Depends(get_db),
                  user: User = Depends(require_editor)) -> dict[str, Any]:
    p = get_project_or_404(project_id, db)
    if data.name is not None:
        p.name = data.name.strip() or p.name
    if data.description is not None:
        p.description = data.description
    if data.status in ("draft", "analyzed", "archived"):
        p.status = data.status
    db.commit()
    return project_out(db, p)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_editor)) -> dict[str, Any]:
    p = get_project_or_404(project_id, db)
    if user.role != Role.ADMIN and p.owner_id not in (None, user.id):
        raise HTTPException(403, "Удалить проект может его автор или администратор")
    name = p.name
    db.delete(p)
    db.commit()
    log_action(db, user, "project_deleted", "project", project_id, {"name": name}, client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ документы


@router.get("/projects/{project_id}/documents")
def list_documents(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    get_project_or_404(project_id, db)
    return [doc_brief(d) for d in db.query(Document).filter_by(project_id=project_id).order_by(Document.id).all()]


@router.post("/projects/{project_id}/documents")
async def upload_documents(project_id: int, request: Request, side: str = Form(...),
                           files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                           user: User = Depends(require_editor)) -> list[dict[str, Any]]:
    p = get_project_or_404(project_id, db)
    out, errors = [], []
    for f in files:
        content = await f.read()
        try:
            doc = store_upload(db, p.id, side, f.filename or "file", content, user.id)
        except ValueError as exc:
            errors.append(f"{f.filename}: {exc}")
            continue
        parse_in_background(doc.id)
        out.append(doc_brief(doc))
    if errors and not out:
        raise HTTPException(400, "; ".join(errors))
    p.status = "draft"
    db.commit()
    log_action(db, user, "documents_uploaded", "project", p.id, {"side": side, "files": [d["filename"] for d in out]},
               client_ip(request))
    return out


def _doc_or_404(db: Session, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Документ не найден")
    return d


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    d = _doc_or_404(db, doc_id)
    parsed = d.parsed or {}
    return {**doc_brief(d), "clauses": parsed.get("clauses", []), "abbreviations": parsed.get("abbreviations", {}),
            "records": parsed.get("records", []), "orgchart": parsed.get("orgchart")}


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: int, data: DocPatch, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    d = _doc_or_404(db, doc_id)
    if data.side not in SIDES:
        raise HTTPException(400, "Неверная сторона")
    d.side = data.side
    db.commit()
    return doc_brief(d)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    d = _doc_or_404(db, doc_id)
    path = Path(d.stored_path)
    name = d.filename
    pid = d.project_id
    db.delete(d)
    db.commit()
    path.unlink(missing_ok=True)
    log_action(db, user, "document_deleted", "project", pid, {"file": name}, client_ip(request))
    return {"ok": True}


@router.post("/documents/{doc_id}/reparse")
def reparse_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    d = _doc_or_404(db, doc_id)
    d.status = "uploaded"
    d.parsed = None
    db.commit()
    parse_in_background(d.id)
    return doc_brief(d)


@router.get("/documents/{doc_id}/file")
def download_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = _doc_or_404(db, doc_id)
    return FileResponse(d.stored_path, filename=d.filename)


# ------------------------------------------------------------------ оргструктуры


def _payloads(db: Session, project_id: int, side: str) -> list[dict[str, Any]]:
    docs = db.query(Document).filter_by(project_id=project_id, side=side, status="parsed").order_by(Document.id).all()
    return [doc_payload(d) for d in docs]


def _titles(db: Session, project_id: int) -> dict[int, str]:
    return {d.id: (d.title or d.filename) for d in db.query(Document).filter_by(project_id=project_id).all()}


def _structure(db: Session, p: Project, side: str) -> tuple[dict[str, Any], str, Structure | None]:
    kinds = get_setting(db, "analysis").get("function_kinds")
    data, source = structure_for_side(db, p, side, _payloads(db, p.id, side), kinds, prefer_saved=True)
    row = db.query(Structure).filter_by(project_id=p.id, side=side).first()
    return data, source, row


@router.get("/projects/{project_id}/structures/{side}")
def get_structure(project_id: int, side: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if side not in ("before", "after"):
        raise HTTPException(400, "Сторона: before или after")
    p = get_project_or_404(project_id, db)
    data, source, row = _structure(db, p, side)
    titles = _titles(db, p.id)
    for u in data.get("units", []):
        for f in u.get("functions", []):
            f.setdefault("doc_title", titles.get(f.get("doc_id"), ""))
    return {"side": side, "source": source, "data": data,
            "updated_at": row.updated_at.isoformat() if row and row.updated_at else None}


@router.put("/projects/{project_id}/structures/{side}")
def save_structure(project_id: int, side: str, data: StructureIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_editor)):
    p = get_project_or_404(project_id, db)
    units = []
    ids = set()
    for u in data.units:
        uid = str(u.get("id") or f"m{uuid.uuid4().hex[:6]}")
        if uid in ids:
            continue
        ids.add(uid)
        name = str(u.get("name", "")).strip() or "Без названия"
        units.append({
            "id": uid, "name": name, "short": str(u.get("short") or ""),
            "type": u.get("type") or unit_type_of(name), "parent_id": u.get("parent_id") or None,
            "head_title": str(u.get("head_title") or ""), "origin": u.get("origin") or "manual",
            "evidence": u.get("evidence") or [], "positions": u.get("positions") or [],
            "functions": [
                {**f, "id": f.get("id") or f"manual:{uuid.uuid4().hex[:8]}",
                 "match_text": f.get("match_text") or f.get("text", ""), "kind": f.get("kind") or "function",
                 "doc_id": f.get("doc_id"), "clause_id": f.get("clause_id") or "", "ref_display": f.get("ref_display") or "",
                 "shared": bool(f.get("shared"))}
                for f in (u.get("functions") or []) if str(f.get("text", "")).strip()
            ],
        })
    for u in units:
        if u["parent_id"] not in ids:
            u["parent_id"] = None
    # защита от циклов
    by_id = {u["id"]: u for u in units}
    for u in units:
        seen, cur = {u["id"]}, u
        while cur.get("parent_id"):
            if cur["parent_id"] in seen:
                cur["parent_id"] = None
                break
            seen.add(cur["parent_id"])
            cur = by_id[cur["parent_id"]]
    row = db.query(Structure).filter_by(project_id=p.id, side=side).first()
    payload = {"side": side, "units": units, "unassigned": (row.data or {}).get("unassigned", []) if row else [],
               "subordination": (row.data or {}).get("subordination", []) if row else [],
               "coi_mentions": (row.data or {}).get("coi_mentions", []) if row else []}
    if row:
        row.data, row.source, row.updated_by = payload, "manual", user.id
    else:
        db.add(Structure(project_id=p.id, side=side, data=payload, source="manual", updated_by=user.id))
    db.commit()
    log_action(db, user, "structure_saved", "project", p.id, {"side": side, "units": len(units)}, client_ip(request))
    return {"side": side, "source": "manual", "data": payload}


@router.post("/projects/{project_id}/structures/{side}/rebuild")
def rebuild_structure(project_id: int, side: str, db: Session = Depends(get_db), user: User = Depends(require_editor)):
    p = get_project_or_404(project_id, db)
    kinds = get_setting(db, "analysis").get("function_kinds")
    data, source = structure_for_side(db, p, side, _payloads(db, p.id, side), kinds, prefer_saved=False)
    return {"side": side, "source": source, "data": data}


@router.post("/projects/{project_id}/structures/{side}/recognize")
async def recognize_chart(project_id: int, side: str, file: UploadFile = File(...), mode: str = Form("auto"),
                          db: Session = Depends(get_db), user: User = Depends(require_editor)) -> dict[str, Any]:
    """Распознаёт схему оргструктуры (фото/скан/PDF) и возвращает редактируемый черновик (без сохранения)."""
    get_project_or_404(project_id, db)
    content = await file.read()
    ext = Path(file.filename or "x.png").suffix.lower()
    is_pdf = ext == ".pdf"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        path = Path(tmp.name)
    try:
        llm = get_llm(db)
        result: dict[str, Any] | None = None
        if mode in ("auto", "vision") and llm.vision_enabled:
            try:
                result = extract_with_vision(llm, path, is_pdf)
            except (LLMError, ValueError) as exc:
                if mode == "vision":
                    raise HTTPException(502, f"Vision-модель: {exc}")
        if result is None or not result.get("units"):
            result = extract_orgchart_from_file(path, is_pdf=is_pdf)
        # превью исходного изображения для сравнения «оригинал ↔ распознанное»
        if is_pdf:
            import fitz

            doc = fitz.open(str(path))
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            preview = pix.tobytes("png")
            doc.close()
        else:
            from PIL import Image

            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            preview = buf.getvalue()
        result["preview"] = "data:image/png;base64," + base64.b64encode(preview).decode()
        result["units"] = [{**u, "type": unit_type_of(u["name"]), "functions": [], "positions": [],
                            "origin": "import"} for u in result.get("units", [])]
        return result
    finally:
        path.unlink(missing_ok=True)


@router.get("/projects/{project_id}/structures/{side}/chart.png")
def structure_chart(project_id: int, side: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = get_project_or_404(project_id, db)
    data, _, _ = _structure(db, p, side)
    png = render_chart([{"id": u["id"], "name": u["name"], "short": u.get("short"), "parent_id": u.get("parent_id")}
                        for u in data["units"]], title=p.name)
    return Response(png, media_type="image/png")


@router.post("/projects/{project_id}/structures/{side}/preview")
def preview_regulation(project_id: int, side: str, data: PreviewIn, db: Session = Depends(get_db),
                       user: User = Depends(current_user)) -> dict[str, Any]:
    p = get_project_or_404(project_id, db)
    struct, _, _ = _structure(db, p, side)
    titles = _titles(db, p.id)
    for u in struct["units"]:
        for f in u.get("functions", []):
            f.setdefault("doc_title", titles.get(f.get("doc_id"), ""))
    if not any(u["id"] == data.unit_id for u in struct["units"]):
        raise HTTPException(404, "Подразделение не найдено")
    org = get_setting(db, "org")
    blocks = regulation_blocks(struct, data.unit_id, data.lang, org, data.include_sources)
    return {"html": blocks_to_html(blocks)}


@router.post("/projects/{project_id}/structures/{side}/package")
def generate_package(project_id: int, side: str, data: PackageIn, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require_editor)) -> dict[str, Any]:
    p = get_project_or_404(project_id, db)
    struct, _, _ = _structure(db, p, side)
    if not struct.get("units"):
        raise HTTPException(400, "Оргструктура пуста: загрузите документы или создайте структуру")
    org = get_setting(db, "org")
    translations: dict[str, str] = {}
    if "kz" in data.langs and data.translate_kz:
        llm = get_llm(db)
        if llm.enabled:
            from ..analysis import prompts

            texts = list({f["text"] for u in struct["units"] for f in u.get("functions", [])})[:120]
            for t in texts:
                try:
                    translations[t] = llm.complete(prompts.SYSTEM_ANALYST, prompts.TRANSLATE_KZ.format(text=t),
                                                   max_tokens=400)
                except LLMError:
                    break
    zip_bytes = build_package(struct, org, [x for x in data.langs if x in ("ru", "kz")] or ["ru"], data.unit_ids,
                              _titles(db, p.id), data.include_sources, translations)
    folder = get_settings().generated_dir / str(p.id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"Пакет_документов_{'после' if side == 'after' else 'до'}_{uuid.uuid4().hex[:6]}.zip"
    path = folder / name
    path.write_bytes(zip_bytes)
    gf = GeneratedFile(project_id=p.id, kind="package", title="Пакет документов по оргструктуре", filename=name,
                       path=str(path), lang=",".join(data.langs), created_by=user.id)
    db.add(gf)
    db.commit()
    log_action(db, user, "package_generated", "project", p.id, {"side": side, "langs": data.langs}, client_ip(request))
    return {"id": gf.id, "filename": name, "size": len(zip_bytes)}


@router.get("/projects/{project_id}/structure-diff")
def structure_diff(project_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict[str, Any]:
    """Совмещённая схема «до/после» для визуализации изменений."""
    p = get_project_or_404(project_id, db)
    before, _, _ = _structure(db, p, "before")
    after, _, _ = _structure(db, p, "after")
    run = (db.query(AnalysisRun).filter_by(project_id=p.id, status="done").order_by(AnalysisRun.id.desc()).first())
    if run and run.result:
        units_status = run.result["units"]
    else:
        settings = get_setting(db, "analysis")
        units_status = Comparator(before, after, settings, Similarity(), _titles(db, p.id)).run()["units"]
    return merge_structures(before, after, units_status)


def merge_structures(before: dict[str, Any], after: dict[str, Any], units_status: list[dict[str, Any]]) -> dict[str, Any]:
    b_units = {u["id"]: u for u in before.get("units", [])}
    a_units = {u["id"]: u for u in after.get("units", [])}
    a_status: dict[str, dict[str, Any]] = {}
    b_to_a: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for st in units_status:
        if st["before"] and st["status"] in ("preserved", "renamed") and st["after"]:
            aid = st["after"][0]["id"]
            b_to_a[st["before"]["id"]] = aid
            a_status[aid] = {"status": st["status"], "before_name": st["before"]["name"], "lost": st.get("functions_lost"),
                             "finding_id": st.get("finding_id"), "parent_changed": st.get("parent_changed")}
        elif not st["before"] and st["after"]:
            a_status[st["after"][0]["id"]] = {"status": st["status"], "sources": st.get("sources", []),
                                              "finding_id": st.get("finding_id")}
    for aid, u in a_units.items():
        info = a_status.get(aid, {"status": "preserved"})
        nodes.append({"id": f"a:{aid}", "name": u["name"], "short": u.get("short", ""), "type": u.get("type"),
                      "parent_id": f"a:{u['parent_id']}" if u.get("parent_id") in a_units else None,
                      "head_title": u.get("head_title", ""), "functions": len(u.get("functions", [])), **info})
    for st in units_status:
        if not st["before"] or st["before"]["id"] in b_to_a:
            continue
        bu = b_units.get(st["before"]["id"])
        if not bu:
            continue
        bp = bu.get("parent_id")
        parent = f"a:{b_to_a[bp]}" if bp in b_to_a else (f"b:{bp}" if bp in b_units else None)
        nodes.append({"id": f"b:{bu['id']}", "name": bu["name"], "short": bu.get("short", ""), "type": bu.get("type"),
                      "parent_id": parent, "head_title": bu.get("head_title", ""),
                      "functions": len(bu.get("functions", [])), "status": st["status"],
                      "lost": st.get("functions_lost"), "finding_id": st.get("finding_id"),
                      "destinations": st.get("destinations", [])})
        for a in st.get("after", []):
            if a["id"] in a_units:
                links.append({"from": f"b:{bu['id']}", "to": f"a:{a['id']}", "kind": "successor"})
    return {"nodes": nodes, "links": links}
