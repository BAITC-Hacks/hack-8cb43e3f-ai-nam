"""Демо-проекты из контрольных комплектов (см. samples/README.md).

* telecom — синтетический комплект АО «ДемоТелеком» с заранее известными изменениями (samples/demo);
* audit   — документы организатора хакатона: Положение о внутреннем аудите, ред. № 8 → № 9 (samples/organizer).
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..config import ROOT_DIR
from ..models import Project
from .documents import parse_document, store_upload

SIDES = ("before", "after", "requirements", "benchmark")

DEMO_SETS: dict[str, dict[str, str | Path]] = {
    "telecom": {
        "dir": ROOT_DIR / "samples" / "demo",
        "name": "Демо: реорганизация ИТ-блока АО «ДемоТелеком»",
        "description": ("Контрольный комплект: ДИТ разделён на Департамент цифровой инфраструктуры и Службу ИБ, "
                        "функция «ИТ-стратегия» утрачена, мониторинг договоров дублируется, в СИБ совмещены "
                        "предоставление и проверка прав доступа."),
    },
    "audit": {
        "dir": ROOT_DIR / "samples" / "organizer",
        "name": "Документы организатора: Положение о внутреннем аудите (ред. 8 → ред. 9)",
        "description": ("Тестовые документы организатора хакатона: две редакции Положения о внутреннем аудите "
                        "АО «Компания». Созданы новые департаменты, перераспределены функции директоров."),
    },
}


def available_sets() -> list[dict[str, str]]:
    return [{"key": k, "name": str(v["name"])} for k, v in DEMO_SETS.items()
            if (Path(v["dir"]) / "before").exists() and (Path(v["dir"]) / "after").exists()]


def demo_available() -> bool:
    return bool(available_sets())


def create_demo_project(db: Session, user_id: int | None, key: str = "telecom") -> Project:
    spec = DEMO_SETS.get(key)
    folder = Path(spec["dir"]) if spec else None
    if not spec or not folder or not (folder / "before").exists():
        raise ValueError(f"Демо-комплект «{key}» не найден")
    p = Project(name=str(spec["name"]), description=str(spec["description"]), owner_id=user_id, is_demo=True)
    db.add(p)
    db.commit()
    for side in SIDES:
        sub = folder / side
        if not sub.exists():
            continue
        for f in sorted(sub.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                doc = store_upload(db, p.id, side, f.name, f.read_bytes(), user_id)
                parse_document(db, doc)
    return p
