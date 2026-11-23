from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BizError, not_found
from app.models import ApprovalTask
from app.security import CurrentUser

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
EXPIRED = "EXPIRED"
MAX_CONTENT = 20_000


def to_vo(task: ApprovalTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "runId": task.run_id,
        "workflowId": task.workflow_id,
        "nodeId": task.node_id,
        "userId": task.user_id,
        "title": task.title,
        "content": task.content,
        "status": task.status,
        "comment": task.decision_comment,
        "decidedBy": task.decided_by,
        "expiresAt": task.expires_at.isoformat() if task.expires_at else None,
        "decidedAt": task.decided_at.isoformat() if task.decided_at else None,
        "createdAt": task.created_at.isoformat() if task.created_at else None,
    }


def create(session: Session, run_id: str, workflow_id: int | None, node_id: str, user_id: int | None,
           title: str, content: str | None, expires_in_seconds: int | None) -> dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise BizError("审批标题不能为空")
    content = (content or "").strip()
    if len(content) > MAX_CONTENT:
        raise BizError(f"审批内容不能超过 {MAX_CONTENT} 字")
    seconds = 300 if expires_in_seconds is None else max(30, min(1800, expires_in_seconds))
    task = ApprovalTask(
        run_id=run_id,
        workflow_id=workflow_id,
        node_id=node_id,
        user_id=user_id,
        title=title,
        content=content,
        status=PENDING,
        expires_at=datetime.now() + timedelta(seconds=seconds),
    )
    session.add(task)
    session.flush()
    return to_vo(task)


def get(session: Session, task_id: int) -> dict[str, Any]:
    task = _require(session, task_id)
    _expire_if_needed(session, task)
    return to_vo(task)


def list_tasks(session: Session, user: CurrentUser | None, status: str | None) -> list[dict[str, Any]]:
    query = select(ApprovalTask).where(ApprovalTask.deleted == 0)
    if user is not None and not user.is_admin:
        query = query.where(ApprovalTask.user_id == user.id)
    if status and status.strip():
        query = query.where(ApprovalTask.status == status.strip().upper())
    rows = session.scalars(query.order_by(ApprovalTask.id.desc()).limit(200)).all()
    for task in rows:
        _expire_if_needed(session, task)
    return [to_vo(task) for task in rows]


def decide(session: Session, task_id: int, approved: bool, comment: str | None,
           user: CurrentUser) -> dict[str, Any]:
    task = _require(session, task_id)
    _expire_if_needed(session, task)
    if task.status != PENDING:
        raise BizError(f"审批已处理或已过期: {task.status}")
    if user is None or (not user.is_admin and (task.user_id is None or task.user_id != user.id)):
        raise not_found(f"审批任务不存在: {task_id}")
    task.status = APPROVED if approved else REJECTED
    value = (comment or "").strip()
    task.decision_comment = value[:1000]
    task.decided_by = user.id
    task.decided_at = datetime.now()
    session.flush()
    return to_vo(task)


def _require(session: Session, task_id: int | None) -> ApprovalTask:
    task = session.get(ApprovalTask, task_id) if task_id is not None else None
    if task is None or task.deleted:
        raise not_found(f"审批任务不存在: {task_id}")
    return task


def _expire_if_needed(session: Session, task: ApprovalTask) -> None:
    if task.status != PENDING:
        return
    if task.expires_at is not None and task.expires_at < datetime.now():
        task.status = EXPIRED
        task.decided_at = datetime.now()
        session.flush()
