from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Header
from fastapi.responses import JSONResponse

from ..db import text_or_none
from ..result import error, success
from ..security import auth_service

router = APIRouter(prefix="/api/auth", tags=["认证接口"])


@router.post("/login")
def login(payload: Optional[dict] = Body(default=None)):
    payload = payload or {}
    username = text_or_none(payload.get("username"))
    password = text_or_none(payload.get("password"))
    if not username:
        return JSONResponse(status_code=400, content=error("用户名不能为空", 400))
    if not password:
        return JSONResponse(status_code=400, content=error("密码不能为空", 400))
    tokens = auth_service.login(username, password)
    if tokens is None:
        return error("用户名或密码错误")
    return success(tokens)


@router.post("/logout")
def logout(payload: Optional[dict] = Body(default=None)):
    payload = payload or {}
    auth_service.logout(text_or_none(payload.get("refreshToken")))
    return success()


@router.post("/refresh")
def refresh(payload: Optional[dict] = Body(default=None)):
    payload = payload or {}
    refresh_token = text_or_none(payload.get("refreshToken"))
    if not refresh_token:
        return {"code": 401, "message": "Refresh Token 不能为空", "data": None}
    tokens = auth_service.refresh(refresh_token)
    if tokens is None:
        return {"code": 401, "message": "Refresh Token 无效或已过期", "data": None}
    return success(tokens)


@router.get("/current")
def current(authorization: Optional[str] = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        username = auth_service.username_by_token(authorization[7:])
        if username:
            return success({"username": username})
    return {"code": 401, "message": "未认证", "data": None}
