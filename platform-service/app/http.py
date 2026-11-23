from __future__ import annotations

from typing import Any

from fastapi import Request

from app.errors import BizError, unauthorized
from app.security import CurrentUser


def current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if user is None:
        raise unauthorized("未登录或 token 缺失")
    return user


def optional_user(request: Request) -> CurrentUser | None:
    return getattr(request.state, "user", None)


def body(request: Request) -> dict[str, Any]:
    value = getattr(request.state, "body", None)
    return value if isinstance(value, dict) else {}


def require_text(payload: dict[str, Any], key: str, message: str, maximum: int | None = None) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BizError(message)
    text = value.strip()
    if maximum is not None and len(text) > maximum:
        raise BizError(f"{key} 不能超过 {maximum} 字符")
    return text


def limit_text(value: Any, maximum: int) -> str:
    return "" if value is None else str(value)[:maximum]
