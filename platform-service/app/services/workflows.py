from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import not_found
from app.flow import count_nodes, validate_structure
from app.models import Workflow, WorkflowTrigger, WorkflowVersion
from app.security import CurrentUser
from app.serialization import dumps, iso, loads, page

log = logging.getLogger("agentflow.workflows")
EMPTY_FLOW = {"nodes": [], "edges": []}


def read_flow(text: str | None) -> dict[str, Any]:
    value = loads(text)
    return value if isinstance(value, dict) else EMPTY_FLOW


def _safe_flow(text: str | None) -> dict[str, Any]:
    value = loads(text)
    return value if isinstance(value, dict) else EMPTY_FLOW


def get_entity(session: Session, workflow_id: int, user: CurrentUser | None = None) -> Workflow:
    entity = session.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0))
    if entity is None:
        raise not_found(f"工作流不存在: {workflow_id}")
    if (
        user is not None
        and entity.user_id is not None
        and entity.user_id != user.id
        and not user.is_admin
    ):
        raise not_found(f"工作流不存在: {workflow_id}")
    return entity


def to_summary(workflow: Workflow) -> dict[str, Any]:
    flow = _safe_flow(workflow.flow_data)
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "engineType": workflow.engine_type,
        "status": workflow.status,
        "version": workflow.version,
        "publishedVersion": workflow.published_version,
        "nodeCount": count_nodes(flow),
        "createdAt": iso(workflow.created_at),
        "updatedAt": iso(workflow.updated_at),
    }


def to_detail(workflow: Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "engineType": workflow.engine_type,
        "status": workflow.status,
        "version": workflow.version,
        "publishedVersion": workflow.published_version,
        "publishedAt": iso(workflow.published_at),
        "flow": _safe_flow(workflow.flow_data),
        "createdAt": iso(workflow.created_at),
        "updatedAt": iso(workflow.updated_at),
    }


def _to_version(version: WorkflowVersion, workflow: Workflow, with_flow: bool = False) -> dict[str, Any]:
    return {
        "id": version.id,
        "workflowId": version.workflow_id,
        "version": version.version,
        "name": version.name,
        "description": version.description,
        "engineType": version.engine_type,
        "note": version.note,
        "createdBy": version.created_by,
        "createdAt": iso(version.created_at),
        "published": version.version == workflow.published_version,
        "current": version.version == workflow.version,
        "flow": read_flow(version.flow_data) if with_flow else None,
    }


def list_page(session: Session, current: int, size: int, keyword: str | None, user: CurrentUser) -> dict[str, Any]:
    current = max(1, current)
    size = max(1, size)
    conditions = [Workflow.deleted == 0, Workflow.user_id == user.id]
    if keyword and keyword.strip():
        conditions.append(Workflow.name.like(f"%{keyword.strip()}%"))
    total = session.scalar(select(func.count()).select_from(Workflow).where(*conditions)) or 0
    rows = session.scalars(
        select(Workflow)
        .where(*conditions)
        .order_by(Workflow.updated_at.desc(), Workflow.id.desc())
        .offset((current - 1) * size)
        .limit(size)
    ).all()
    return page([to_summary(item) for item in rows], int(total), current, size)


def create(session: Session, name: str, description: str | None, engine_type: str | None, status: int | None,
           flow: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
    validate_structure(flow)
    entity = Workflow(
        name=name,
        description=description,
        engine_type=engine_type or "langgraph",
        flow_data=dumps(flow),
        status=1 if status is None else status,
        version=1,
        user_id=user.id,
    )
    session.add(entity)
    session.flush()
    _save_snapshot(session, entity, "初始版本", user.id)
    return to_detail(entity)


def update(session: Session, workflow_id: int, name: str, description: str | None, engine_type: str | None,
           status: int | None, flow: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
    validate_structure(flow)
    entity = get_entity(session, workflow_id, user)
    entity.name = name
    entity.description = description
    if engine_type is not None:
        entity.engine_type = engine_type
    entity.flow_data = dumps(flow)
    if entity.published_version is not None:
        entity.status = 2
    elif status is not None:
        entity.status = status
    entity.version = (entity.version or 1) + 1
    session.flush()
    _save_snapshot(session, entity, f"保存 v{entity.version}", user.id)
    return to_detail(entity)


def delete(session: Session, workflow_id: int, user: CurrentUser) -> None:
    entity = get_entity(session, workflow_id, user)
    trigger_ids = session.scalars(
        select(WorkflowTrigger.id).where(WorkflowTrigger.workflow_id == entity.id, WorkflowTrigger.deleted == 0)
    ).all()
    for trigger_id in trigger_ids:
        trigger = session.get(WorkflowTrigger, trigger_id)
        if trigger is not None:
            trigger.deleted = 1
    for version in session.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == entity.id)).all():
        session.delete(version)
    entity.deleted = 1
    session.flush()
    from app.services.scheduler import get_scheduler

    for trigger_id in trigger_ids:
        get_scheduler().refresh(trigger_id)


def duplicate(session: Session, workflow_id: int, user: CurrentUser) -> dict[str, Any]:
    source = get_entity(session, workflow_id, user)
    copy = Workflow(
        name=source.name + " 副本",
        description=source.description,
        engine_type=source.engine_type,
        flow_data=source.flow_data,
        status=1,
        version=1,
        user_id=user.id,
    )
    session.add(copy)
    session.flush()
    _save_snapshot(session, copy, f"复制自工作流 #{source.id}", user.id)
    return to_detail(copy)


def list_versions(session: Session, workflow_id: int, user: CurrentUser) -> list[dict[str, Any]]:
    entity = get_entity(session, workflow_id, user)
    rows = session.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
    ).all()
    return [_to_version(item, entity) for item in rows]


def version_detail(session: Session, workflow_id: int, version: int, user: CurrentUser) -> dict[str, Any]:
    entity = get_entity(session, workflow_id, user)
    snapshot = _find_version(session, workflow_id, version)
    if snapshot is None:
        raise not_found(f"版本不存在: v{version}")
    return _to_version(snapshot, entity, True)


def rollback(session: Session, workflow_id: int, version: int, user: CurrentUser) -> dict[str, Any]:
    entity = get_entity(session, workflow_id, user)
    target = _find_version(session, workflow_id, version)
    if target is None:
        raise not_found(f"版本不存在: v{version}")
    entity.flow_data = target.flow_data
    entity.engine_type = target.engine_type
    entity.version = (entity.version or 1) + 1
    session.flush()
    _save_snapshot(session, entity, f"回滚自 v{version}", user.id)
    return to_detail(entity)


def publish(session: Session, workflow_id: int, user: CurrentUser) -> dict[str, Any]:
    entity = get_entity(session, workflow_id, user)
    _ensure_snapshot(session, entity, "发布前快照", user.id)
    entity.published_version = entity.version
    entity.published_at = datetime.now()
    entity.status = 2
    session.flush()
    return to_detail(entity)


def unpublish(session: Session, workflow_id: int, user: CurrentUser) -> dict[str, Any]:
    entity = get_entity(session, workflow_id, user)
    entity.published_version = None
    entity.published_at = None
    entity.status = 1
    session.flush()
    return to_detail(entity)


def flow_for_run(session: Session, workflow: Workflow, prefer_published: bool) -> tuple[dict[str, Any], int | None, bool]:
    if prefer_published and workflow.published_version is not None:
        snapshot = _find_version(session, workflow.id, workflow.published_version)
        if snapshot is not None:
            return read_flow(snapshot.flow_data), snapshot.version, True
    return read_flow(workflow.flow_data), workflow.version, False


def _find_version(session: Session, workflow_id: int, version: int | None) -> WorkflowVersion | None:
    if version is None:
        return None
    return session.scalar(
        select(WorkflowVersion).where(
            WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.version == version
        )
    )


def _ensure_snapshot(session: Session, workflow: Workflow, note: str, user_id: int) -> None:
    if _find_version(session, workflow.id, workflow.version) is None:
        _save_snapshot(session, workflow, note, user_id)


def _save_snapshot(session: Session, workflow: Workflow, note: str, user_id: int) -> None:
    snapshot = WorkflowVersion(
        workflow_id=workflow.id,
        version=workflow.version or 1,
        name=workflow.name,
        description=workflow.description,
        engine_type=workflow.engine_type,
        flow_data=workflow.flow_data,
        note=note,
        created_by=user_id,
    )
    session.add(snapshot)


def flow_by_id(session: Session, workflow_id: int) -> dict[str, Any]:
    return read_flow(get_entity(session, workflow_id).flow_data)
