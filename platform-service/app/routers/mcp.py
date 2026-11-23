from __future__ import annotations

from fastapi import APIRouter, Request

from app.database import session_scope
from app.errors import BizError
from app.http import current_user
from app.serialization import ok
from app.services.mcp import McpService

router = APIRouter(prefix="/api/mcp-servers", tags=["mcp"])
service = McpService()


@router.get("")
def list_servers(request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.list_servers(session, user))


@router.post("")
def create_server(request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    _validate(payload)
    with session_scope() as session:
        return ok(service.save(session, None, payload, user))


@router.put("/{server_id}")
def update_server(server_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    _validate(payload)
    with session_scope() as session:
        return ok(service.save(session, server_id, payload, user))


@router.delete("/{server_id}")
def delete_server(server_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        service.delete(session, server_id, user)
        return ok()


@router.post("/{server_id}/discover")
def discover(server_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.discover(session, server_id, user))


@router.get("/{server_id}/tools")
def tools(server_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.tools(session, server_id, user))


def _validate(payload: dict) -> None:
    if not str(payload.get("name") or "").strip():
        raise BizError("name 不能为空")
    if not str(payload.get("url") or "").strip():
        raise BizError("url 不能为空")
