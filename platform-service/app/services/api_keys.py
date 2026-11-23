from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BizError, not_found
from app.models import ApiKey, User
from app.security import CurrentUser, generate_api_key, hash_password, mask_api_key, verify_password


def issue(session: Session, name: str, owner_user_id: int, expires_at: datetime | None) -> dict[str, Any]:
    owner = session.get(User, owner_user_id)
    if owner is None or owner.deleted:
        raise not_found(f"拥有者用户不存在: {owner_user_id}")
    if expires_at is not None and expires_at <= datetime.now():
        raise BizError("过期时间必须晚于当前时间")
    raw = generate_api_key()
    entity = ApiKey(
        name=name,
        key_hash=hash_password(raw),
        owner_user_id=owner.id,
        enabled=1,
        expires_at=expires_at,
    )
    session.add(entity)
    session.flush()
    return {
        "id": entity.id,
        "name": name,
        "rawKey": raw,
        "maskedKey": mask_api_key(raw),
        "ownerUsername": owner.username,
        "expiresAt": expires_at.isoformat() if expires_at else None,
    }


def list_keys(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(ApiKey).order_by(ApiKey.id.desc())).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "maskedKey": "af_****",
            "ownerUserId": item.owner_user_id,
            "enabled": item.enabled,
            "expiresAt": item.expires_at.isoformat() if item.expires_at else None,
            "createdAt": item.created_at.isoformat() if item.created_at else None,
        }
        for item in rows
    ]


def revoke(session: Session, key_id: int) -> None:
    entity = session.get(ApiKey, key_id)
    if entity is None:
        raise not_found(f"API Key 不存在: {key_id}")
    session.delete(entity)


def authenticate(session: Session, raw_key: str) -> CurrentUser | None:
    if not raw_key or not raw_key.strip():
        return None
    candidates = session.scalars(select(ApiKey).where(ApiKey.enabled == 1)).all()
    for item in candidates:
        if verify_password(raw_key, item.key_hash):
            if item.expires_at is not None and item.expires_at < datetime.now():
                return None
            owner = session.get(User, item.owner_user_id)
            if owner is None or owner.deleted:
                return None
            return CurrentUser(owner.id, "apikey:" + item.name, owner.role)
    return None
