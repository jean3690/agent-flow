from __future__ import annotations

from fastapi import APIRouter, Request

from app.database import session_scope
from app.http import current_user, require_text
from app.serialization import ok
from app.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(request: Request):
    payload = request.state.body or {}
    username = require_text(payload, "username", "username 不能为空")
    password = require_text(payload, "password", "password 不能为空")
    with session_scope() as session:
        return ok(auth_service.login(session, username, password))


@router.get("/me")
def me(request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(auth_service.current(session, user))
