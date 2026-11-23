from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events
from ..db import SessionLocal, get_db, jload, text_or_none
from ..engine import DagEngine, dag_engine, langgraph_engine, select_engine
from ..models import ExecutionRecord, ExecutionSnapshot, ExecutionVariable, Workflow
from ..result import error, success
from ..security import auth_service
from ..serializers import execution_response, snapshot_to_dict, variable_to_dict

logger = logging.getLogger("paiagent.executions")

router = APIRouter(prefix="/api/workflows", tags=["工作流执行接口"])

_DONE = object()


def _find_workflow(db: Session, workflow_id: int) -> Optional[Workflow]:
    return db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.deleted == 0)
    ).scalar_one_or_none()


@router.post("/{workflow_id}/execute")
def execute_workflow(workflow_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    input_data = text_or_none(payload.get("inputData"))
    if not input_data:
        return JSONResponse(status_code=400, content=error("输入数据不能为空", 400))

    workflow = _find_workflow(db, workflow_id)
    if workflow is None:
        return error("工作流不存在")

    try:
        engine = select_engine(workflow)
        return success(engine.execute(db, workflow, input_data, None))
    except Exception as exc:
        logger.exception("工作流执行失败")
        return error(f"工作流执行失败: {exc}")


@router.get("/{workflow_id}/executions/latest")
def latest_execution(workflow_id: int, db: Session = Depends(get_db)):
    workflow = _find_workflow(db, workflow_id)
    if workflow is None:
        return error("工作流不存在")

    record = db.execute(
        select(ExecutionRecord)
        .where(ExecutionRecord.flow_id == workflow_id, ExecutionRecord.deleted == 0)
        .order_by(ExecutionRecord.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if record is None:
        return success(None)
    return success(execution_response(record))


@router.get("/{workflow_id}/executions/{execution_id}/snapshots")
def get_execution_snapshots(workflow_id: int, execution_id: int, db: Session = Depends(get_db)):
    record = db.execute(
        select(ExecutionRecord).where(
            ExecutionRecord.id == execution_id, ExecutionRecord.deleted == 0
        )
    ).scalar_one_or_none()
    if record is None or record.flow_id != workflow_id:
        return error("执行记录不存在")

    snapshots = db.execute(
        select(ExecutionSnapshot)
        .where(ExecutionSnapshot.execution_id == execution_id)
        .order_by(ExecutionSnapshot.execution_order.asc())
    ).scalars()
    return success([snapshot_to_dict(snapshot) for snapshot in snapshots])


@router.get("/{workflow_id}/executions/{execution_id}/variables")
def get_execution_variables(workflow_id: int, execution_id: int, db: Session = Depends(get_db)):
    record = db.execute(
        select(ExecutionRecord).where(
            ExecutionRecord.id == execution_id, ExecutionRecord.deleted == 0
        )
    ).scalar_one_or_none()
    if record is None or record.flow_id != workflow_id:
        return error("执行记录不存在")

    variables = db.execute(
        select(ExecutionVariable)
        .where(ExecutionVariable.execution_id == execution_id)
        .order_by(ExecutionVariable.variable_name.asc())
    ).scalars()
    return success([variable_to_dict(variable) for variable in variables])


@router.post("/{workflow_id}/executions/{execution_id}/resume")
def resume_execution(
    workflow_id: int,
    execution_id: int,
    payload: Optional[dict] = Body(default=None),
    db: Session = Depends(get_db),
):
    workflow = _find_workflow(db, workflow_id)
    if workflow is None:
        return error("工作流不存在")

    try:
        engine = select_engine(workflow)
        if not isinstance(engine, DagEngine):
            return error("当前执行引擎暂不支持断点续执行")
        return success(engine.resume(db, workflow, execution_id, payload or {}, None))
    except Exception as exc:
        logger.exception("断点续执行失败")
        return error(f"断点续执行失败: {exc}")


def _valid_stream_token(token: Optional[str], authorization: Optional[str]) -> bool:
    if authorization and authorization.startswith("Bearer "):
        authorization = authorization[7:]
    candidate = authorization or token
    if not candidate:
        return False
    return auth_service.validate_token(candidate)


@router.get("/{workflow_id}/execute/stream")
async def execute_workflow_stream(
    workflow_id: int,
    inputData: str = Query(default=""),
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    if not _valid_stream_token(token, authorization):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "未认证或认证已过期"},
        )

    async def event_generator():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def emit(payload: dict, event_name: Optional[str] = None) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (event_name or payload.get("eventType"), payload))

        def worker() -> None:
            db = SessionLocal()
            try:
                workflow = _find_workflow(db, workflow_id)
                if workflow is None:
                    emit(events.workflow_complete("FAILED", "工作流不存在", 0), "ERROR")
                    return
                engine = select_engine(workflow)
                engine.execute(db, workflow, inputData, emit)
            except Exception as exc:
                logger.exception("工作流执行失败")
                emit(events.workflow_complete("FAILED", str(exc), 0), "ERROR")
            finally:
                db.close()
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        import threading

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                event_name, payload = item
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                yield f"event: {event_name}\ndata: {data}\n\n"
        finally:
            thread.join(timeout=1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
