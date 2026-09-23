"""Хранение и разбор загруженных документов."""
from __future__ import annotations

import hashlib
import re
import threading
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import Document
from ..parsing.parse import SUPPORTED, parse_file

SIDES = ("before", "after", "requirements", "benchmark")

_parse_locks: dict[int, threading.Lock] = {}


def safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\-() ]+", "_", name, flags=re.UNICODE).strip() or "file"
    return name[:180]


def store_upload(db: Session, project_id: int, side: str, filename: str, content: bytes,
                 user_id: int | None) -> Document:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Формат {ext or '(без расширения)'} не поддерживается. "
                         f"Допустимо: {', '.join(sorted(SUPPORTED))}")
    if side not in SIDES:
        raise ValueError("Неверная сторона комплекта")
    settings = get_settings()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError(f"Файл больше {settings.max_upload_mb} МБ")
    folder = settings.uploads_dir / str(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(content).hexdigest()[:10]
    stored = folder / f"{uuid.uuid4().hex[:8]}_{digest}{ext}"
    stored.write_bytes(content)
    doc = Document(project_id=project_id, side=side, filename=safe_filename(filename), stored_path=str(stored),
                   size=len(content), mime=ext.lstrip("."), status="uploaded", uploaded_by=user_id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def parse_document(db: Session, doc: Document) -> Document:
    lock = _parse_locks.setdefault(doc.id, threading.Lock())
    with lock:
        db.refresh(doc)
        if doc.status == "parsed" and doc.parsed:
            return doc
        doc.status = "processing"
        db.commit()
        try:
            parsed = parse_file(Path(doc.stored_path), doc.filename)
            doc.parsed = parsed
            doc.title = parsed.get("title") or doc.filename
            doc.doc_kind = parsed.get("doc_kind", "")
            doc.parse_method = parsed.get("method", "")
            doc.pages = parsed.get("pages", 0) or 0
            doc.clause_count = len(parsed.get("clauses", []))
            doc.status = "parsed"
            doc.error = ""
        except Exception as exc:  # noqa: BLE001 - ошибку показываем пользователю
            doc.status = "error"
            doc.error = str(exc)[:1000]
        db.commit()
        return doc


def parse_in_background(doc_id: int) -> None:
    def work() -> None:
        db = SessionLocal()
        try:
            doc = db.get(Document, doc_id)
            if doc:
                parse_document(db, doc)
        finally:
            db.close()

    threading.Thread(target=work, daemon=True, name=f"parse-{doc_id}").start()


def doc_brief(doc: Document) -> dict:
    parsed = doc.parsed or {}
    return {
        "id": doc.id,
        "side": doc.side,
        "filename": doc.filename,
        "title": doc.title or doc.filename,
        "doc_kind": doc.doc_kind,
        "status": doc.status,
        "error": doc.error,
        "method": doc.parse_method,
        "pages": doc.pages,
        "clause_count": doc.clause_count,
        "size": doc.size,
        "edition": parsed.get("edition", ""),
        "approval": parsed.get("approval", ""),
        "warnings": parsed.get("warnings", []),
        "abbreviations": len(parsed.get("abbreviations") or {}),
        "has_orgchart": bool((parsed.get("orgchart") or {}).get("units")),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }
