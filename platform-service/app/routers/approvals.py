from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.database import session_scope
from app.errors import BizError
from app.http import current_user
from app.serialization import ok
from app.services import approvals

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
def list_approvals(request: Request, status: str | None = Query(default=None)):
    user = current_user(request)
    with session_scope() as session:
        return ok(approvals.list_tasks(session, user, status))


@router.post("/{task_id}/decide")
def decide(task_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    approved = payload.get("approved")
    if not isinstance(approved, bool):
        raise BizError("approved 不能为空")
    comment = payload.get("comment")
    if comment is not None and len(str(comment)) > 1000:
        raise BizError("comment 不能超过 1000 字符")
    with session_scope() as session:
        return ok(approvals.decide(session, task_id, approved, comment, user))
