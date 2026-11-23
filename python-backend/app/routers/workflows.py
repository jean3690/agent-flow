from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db, now, text_or_none
from ..models import Workflow
from ..result import error, success
from ..serializers import workflow_to_dict

router = APIRouter(prefix="/api/workflows", tags=["工作流管理接口"])


def _require_text(value, message: str) -> Optional[JSONResponse]:
    if not text_or_none(value):
        return JSONResponse(status_code=400, content=error(message, 400))
    return None


@router.post("")
def create_workflow(payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    invalid = _require_text(payload.get("name"), "工作流名称不能为空")
    if invalid:
        return invalid
    invalid = _require_text(payload.get("flowData"), "工作流配置数据不能为空")
    if invalid:
        return invalid

    workflow = Workflow()
    workflow.name = str(payload.get("name"))
    workflow.description = payload.get("description")
    workflow.flow_data = str(payload.get("flowData"))
    workflow.engine_type = text_or_none(payload.get("engineType")) or "dag"
    workflow.deleted = 0
    workflow.created_at = now()
    workflow.updated_at = now()
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return success(workflow_to_dict(workflow))


@router.put("/{workflow_id}")
def update_workflow(workflow_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    invalid = _require_text(payload.get("name"), "工作流名称不能为空")
    if invalid:
        return invalid
    invalid = _require_text(payload.get("flowData"), "工作流配置数据不能为空")
    if invalid:
        return invalid

    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0)
    ).scalar_one_or_none()
    if workflow is None:
        return error("工作流不存在")

    workflow.name = str(payload.get("name"))
    workflow.flow_data = str(payload.get("flowData"))
    # MyBatis-Plus default update strategy ignores null fields.
    if payload.get("description") is not None:
        workflow.description = payload.get("description")
    if payload.get("engineType") is not None:
        workflow.engine_type = text_or_none(payload.get("engineType"))
    workflow.updated_at = now()
    db.commit()
    db.refresh(workflow)
    return success(workflow_to_dict(workflow))


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0)
    ).scalar_one_or_none()
    if workflow is not None:
        workflow.deleted = 1
        workflow.updated_at = now()
        db.commit()
    return success()


@router.get("/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db)):
    workflow = db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0)
    ).scalar_one_or_none()
    if workflow is None:
        return error("工作流不存在")
    return success(workflow_to_dict(workflow))


@router.get("")
def list_workflows(db: Session = Depends(get_db)):
    workflows = db.execute(
        select(Workflow)
        .where(Workflow.deleted == 0)
        .order_by(Workflow.updated_at.desc())
    ).scalars()
    return success([workflow_to_dict(workflow) for workflow in workflows])
