from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.database import session_scope
from app.errors import BizError
from app.http import current_user, require_text
from app.serialization import ok
from app.services import workflows
from app.services.execution import get_execution_service

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _save_payload(payload: dict[str, Any]) -> dict[str, Any]:
    name = require_text(payload, "name", "name 不能为空", 128)
    flow = payload.get("flow")
    if not isinstance(flow, dict):
        raise BizError("flow 不能为空")
    return {
        "name": name,
        "description": payload.get("description"),
        "engineType": payload.get("engineType"),
        "status": payload.get("status"),
        "flow": flow,
    }


@router.get("")
def list_workflows(request: Request, page: int = Query(default=1), size: int = Query(default=10),
                   keyword: str | None = Query(default=None)):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.list_page(session, page, size, keyword, user))


@router.post("")
def create_workflow(request: Request):
    user = current_user(request)
    payload = _save_payload(request.state.body or {})
    with session_scope() as session:
        return ok(
            workflows.create(
                session,
                payload["name"],
                payload["description"],
                payload["engineType"],
                payload["status"],
                payload["flow"],
                user,
            )
        )


@router.get("/{workflow_id}")
def detail_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.to_detail(workflows.get_entity(session, workflow_id, user)))


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    payload = _save_payload(request.state.body or {})
    with session_scope() as session:
        return ok(
            workflows.update(
                session,
                workflow_id,
                payload["name"],
                payload["description"],
                payload["engineType"],
                payload["status"],
                payload["flow"],
                user,
            )
        )


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        workflows.delete(session, workflow_id, user)
        return ok()


@router.post("/{workflow_id}/duplicate")
def duplicate_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.duplicate(session, workflow_id, user))


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    state = {"closed": False}

    def emit(event: str, body: str) -> None:
        if state["closed"]:
            return
        if event == "__end__":
            loop.call_soon_threadsafe(queue.put_nowait, None)
        else:
            loop.call_soon_threadsafe(queue.put_nowait, (event, body))

    _, control = await asyncio.to_thread(
        get_execution_service().start_stream, workflow_id, payload, user, emit
    )

    async def stream():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, body = item
                yield f"event: {event}\ndata: {body}\n\n"
        finally:
            state["closed"] = True
            control.client_closed = True

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{workflow_id}/run")
def run_workflow(workflow_id: int, request: Request):
    user = current_user(request)
    return ok(get_execution_service().run_sync(workflow_id, request.state.body or {}, user))


@router.get("/{workflow_id}/versions")
def list_versions(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.list_versions(session, workflow_id, user))


@router.get("/{workflow_id}/versions/{version}")
def version_detail(workflow_id: int, version: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.version_detail(session, workflow_id, version, user))


@router.post("/{workflow_id}/versions/{version}/rollback")
def rollback(workflow_id: int, version: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.rollback(session, workflow_id, version, user))


@router.post("/{workflow_id}/publish")
def publish(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.publish(session, workflow_id, user))


@router.post("/{workflow_id}/unpublish")
def unpublish(workflow_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(workflows.unpublish(session, workflow_id, user))


@router.get("/{workflow_id}/executions")
def workflow_executions(workflow_id: int, request: Request, page: int = Query(default=1),
                        size: int = Query(default=10)):
    user = current_user(request)
    with session_scope() as session:
        return ok(get_execution_service().page(session, page, size, workflow_id, None, user))
