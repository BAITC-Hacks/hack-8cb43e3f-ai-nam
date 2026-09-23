"""Демо-проект из контрольного комплекта samples/demo (см. samples/README.md)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..config import ROOT_DIR
from ..models import Project
from .documents import parse_document, store_upload

DEMO_DIR = ROOT_DIR / "samples" / "demo"
SIDES = ("before", "after", "requirements", "benchmark")


def demo_available() -> bool:
    return (DEMO_DIR / "before").exists() and (DEMO_DIR / "after").exists()


def create_demo_project(db: Session, user_id: int | None) -> Project:
    if not demo_available():
        raise ValueError("Демо-комплект не найден (samples/demo)")
    p = Project(
        name="Демо: реорганизация ИТ-блока АО «ДемоТелеком»",
        description=("Контрольный комплект: ДИТ разделён на Департамент цифровой инфраструктуры и Службу ИБ, "
                     "функция «ИТ-стратегия» утрачена, мониторинг договоров дублируется, в СИБ совмещены "
                     "предоставление и проверка прав доступа."),
        owner_id=user_id,
        is_demo=True,
    )
    db.add(p)
    db.commit()
    for side in SIDES:
        folder = DEMO_DIR / side
        if not folder.exists():
            continue
        for f in sorted(folder.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                doc = store_upload(db, p.id, side, f.name, f.read_bytes(), user_id)
                parse_document(db, doc)
    return p
