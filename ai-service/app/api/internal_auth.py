from secrets import compare_digest

from fastapi import Header, HTTPException

from app.config import get_settings


def require_internal(x_internal_token: str = Header(default="")):
    expected = get_settings().internal_token
    if not expected or not compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=403, detail="仅允许平台内部服务访问")
