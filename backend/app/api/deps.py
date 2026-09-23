from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..core.security import decode_token
from ..db import get_db
from ..models import Project, Role, User

bearer = HTTPBearer(auto_error=False)


def _user_from_token(token: str | None, db: Session, *, scope: str) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 - любые ошибки токена = 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова")
    if payload.get("scope") != scope:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Токен не подходит для этого раздела")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь заблокирован или удалён")
    return user


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> User:
    token = creds.credentials if creds else None
    # Для прямых ссылок на скачивание файлов допускаем токен в query (?token=...)
    if not token and request is not None:
        token = request.query_params.get("token")
    return _user_from_token(token, db, scope="app")


def current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user = _user_from_token(creds.credentials if creds else None, db, scope="admin")
    if user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступ только для администратора")
    return user


def require_editor(user: User = Depends(current_user)) -> User:
    if user.role not in (Role.ADMIN, Role.ANALYST):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав: роль «Наблюдатель»")
    return user


def get_project_or_404(project_id: int, db: Session) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return project


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""
