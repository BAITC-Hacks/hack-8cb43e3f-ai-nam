"""Первичное наполнение: администратор из .env, демо-пользователи и демо-проект."""
from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.security import hash_password
from ..db import SessionLocal
from ..models import Project, Role, User

log = logging.getLogger("seed")

DEMO_USERS = [
    ("analyst@example.com", "analyst12345", "Аналитик (демо)", Role.ANALYST),
    ("viewer@example.com", "viewer12345", "Наблюдатель (демо)", Role.VIEWER),
]


def seed(db: Session) -> None:
    s = get_settings()
    if not db.query(User).filter(User.role == Role.ADMIN).first():
        email = s.admin_email.strip().lower()
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            existing.role = Role.ADMIN
        else:
            db.add(User(email=email, full_name="Администратор", role=Role.ADMIN,
                        password_hash=hash_password(s.admin_password)))
        db.commit()
        log.warning("Создан администратор %s (смените пароль после входа)", email)
    if s.seed_demo:
        for email, pwd, name, role in DEMO_USERS:
            if not db.query(User).filter(User.email == email).first():
                db.add(User(email=email, full_name=name, role=role, password_hash=hash_password(pwd)))
        db.commit()
        if not db.query(Project).first():
            threading.Thread(target=_demo_background, daemon=True, name="demo-seed").start()


def _demo_background() -> None:
    from .agent import start_analysis
    from .demo import create_demo_project, demo_available

    if not demo_available():
        return
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.role == Role.ANALYST).first() or db.query(User).first()
        project = create_demo_project(db, owner.id if owner else None)
        start_analysis(db, project, owner.id if owner else None, {"use_llm": True}, background=False)
    except Exception:  # noqa: BLE001 - демо не должно мешать запуску
        log.exception("Не удалось создать демо-проект")
    finally:
        db.close()
