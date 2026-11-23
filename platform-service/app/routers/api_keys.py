from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from app.database import session_scope
from app.errors import BizError, unauthorized
from app.http import current_user, require_text
from app.serialization import ok
from app.services import api_keys

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _admin(request: Request):
    user = current_user(request)
    if not user.is_admin:
        raise unauthorized("仅管理员可管理 API Key")
    return user


@router.post("")
def create_key(request: Request):
    user = _admin(request)
    payload = request.state.body or {}
    name = require_text(payload, "name", "名称不能为空", 64)
    owner = payload.get("ownerUserId") or user.id
    expires_at = _parse_time(payload.get("expiresAt"))
    with session_scope() as session:
        return ok(api_keys.issue(session, name, int(owner), expires_at))


@router.get("")
def list_keys(request: Request):
    _admin(request)
    with session_scope() as session:
        return ok(api_keys.list_keys(session))


@router.delete("/{key_id}")
def revoke_key(key_id: int, request: Request):
    _admin(request)
    with session_scope() as session:
        api_keys.revoke(session, key_id)
        return ok()


def _parse_time(value) -> datetime | None:  # type: ignore[no-untyped-def]
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise BizError("过期时间格式不合法") from exc
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
