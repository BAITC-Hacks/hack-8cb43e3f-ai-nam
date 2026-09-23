from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.security import create_access_token, hash_password, verify_password
from ..db import get_db
from ..models import Role, User
from ..services.audit import log_action
from .deps import client_ip, current_admin_any, current_user_any, current_user_either

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class ProfileIn(BaseModel):
    full_name: str | None = None
    language: str | None = None


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "language": u.language,
        "must_change_password": u.must_change_password,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


def _authenticate(db: Session, data: LoginIn, request: Request, scope: str) -> dict:
    email = data.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(data.password, user.password_hash):
        log_action(db, None, "login_failed", "user", "", {"email": email, "scope": scope}, client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный e-mail или пароль")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись заблокирована. Обратитесь к администратору")
    if scope == "admin" and user.role != Role.ADMIN:
        log_action(db, user, "admin_login_denied", "user", user.id, {}, client_ip(request))
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Вход в панель администратора доступен только администраторам")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    log_action(db, user, "admin_login" if scope == "admin" else "login", "user", user.id, {}, client_ip(request))
    return {"access_token": create_access_token(user.id, user.role, scope), "token_type": "bearer",
            "scope": scope, "user": user_out(user)}


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Вход в рабочую область (аналитик, наблюдатель, администратор)."""
    return _authenticate(db, data, request, "app")


@router.post("/admin/login")
def admin_login(data: LoginIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Отдельный вход в панель администратора: выдаёт токен с областью действия "admin"."""
    return _authenticate(db, data, request, "admin")


@router.get("/me")
def me(user: User = Depends(current_user_any)) -> dict:
    return user_out(user)


@router.get("/admin/me")
def admin_me(user: User = Depends(current_admin_any)) -> dict:
    return user_out(user)


@router.patch("/me")
def update_me(data: ProfileIn, user: User = Depends(current_user_any), db: Session = Depends(get_db)) -> dict:
    if data.full_name is not None:
        user.full_name = data.full_name.strip()[:255]
    if data.language in ("ru", "kz"):
        user.language = data.language
    db.commit()
    return user_out(user)


@router.post("/change-password")
def change_password(data: ChangePasswordIn, request: Request, user: User = Depends(current_user_either),
                    db: Session = Depends(get_db)) -> dict:
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль указан неверно")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    db.commit()
    log_action(db, user, "password_changed", "user", user.id, {}, client_ip(request))
    return {"ok": True}
