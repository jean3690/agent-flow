from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.database import session_scope
from app.http import current_user
from app.serialization import ok
from app.services.execution import get_execution_service

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("")
def list_executions(request: Request, page: int = Query(default=1), size: int = Query(default=10),
                    workflowId: int | None = Query(default=None), status: str | None = Query(default=None)):
    user = current_user(request)
    with session_scope() as session:
        return ok(get_execution_service().page(session, page, size, workflowId, status, user))


@router.get("/{run_id}")
def execution_detail(run_id: str, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(get_execution_service().detail(session, run_id, user))


@router.post("/{run_id}/cancel")
def cancel_execution(run_id: str, request: Request):
    user = current_user(request)
    with session_scope() as session:
        get_execution_service().cancel(session, run_id, user)
        return ok()


@router.delete("/{run_id}")
def delete_execution(run_id: str, request: Request):
    user = current_user(request)
    with session_scope() as session:
        get_execution_service().delete(session, run_id, user)
        return ok()
