from __future__ import annotations

from fastapi import APIRouter, Request

from app.database import session_scope
from app.http import current_user, require_text
from app.serialization import ok
from app.services import triggers

router = APIRouter(tags=["triggers"])


@router.get("/api/workflows/{workflow_id}/triggers")
def list_triggers(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(triggers.list_triggers(session, workflow_id, user))


@router.post("/api/workflows/{workflow_id}/triggers")
def create_trigger(workflow_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    require_text(payload, "name", "name 不能为空", 128)
    require_text(payload, "type", "type 不能为空", 16)
    with session_scope() as session:
        return ok(triggers.create(session, workflow_id, payload, user))


@router.put("/api/triggers/{trigger_id}")
def update_trigger(trigger_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    require_text(payload, "name", "name 不能为空", 128)
    require_text(payload, "type", "type 不能为空", 16)
    with session_scope() as session:
        return ok(triggers.update_trigger(session, trigger_id, payload, user))


@router.delete("/api/triggers/{trigger_id}")
def delete_trigger(trigger_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        triggers.delete(session, trigger_id, user)
        return ok()


@router.post("/api/triggers/{trigger_id}/run")
def run_trigger(trigger_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(triggers.run_now(session, trigger_id, user))


@router.post("/api/triggers/{trigger_id}/rotate-token")
def rotate_token(trigger_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(triggers.rotate_token(session, trigger_id, user))


@router.post("/api/triggers/webhook/{token}")
def webhook(token: str, request: Request):
    with session_scope() as session:
        return ok(triggers.webhook(session, token, request.state.body))
