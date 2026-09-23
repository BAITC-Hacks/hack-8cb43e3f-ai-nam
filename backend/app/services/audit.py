from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import AuditLog, User


def log_action(
    db: Session,
    user: User | None,
    action: str,
    entity: str = "",
    entity_id: Any = "",
    details: dict[str, Any] | None = None,
    ip: str = "",
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else "",
            action=action,
            entity=entity,
            entity_id=str(entity_id or ""),
            details=details or {},
            ip=ip,
        )
    )
    if commit:
        db.commit()
