from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.api.internal_auth import require_internal
from app.config import get_settings
from app.core.events import EventBus
from app.graph.runner import WorkflowRunner
from app.schemas.execution import ExecutionRequest

router = APIRouter(prefix="/v1", tags=["executions"])

_RUNNING: dict[str, asyncio.Task] = {}


@router.post("/executions")
async def execute(request: ExecutionRequest, x_internal_token: str = Header(default="")):
    require_internal(x_internal_token)
    settings = get_settings()
    if request.run_id and request.run_id in _RUNNING:
        raise HTTPException(status_code=409, detail="执行 runId 已存在")
    if len(_RUNNING) >= settings.max_concurrency:
        raise HTTPException(status_code=503, detail="AI 执行容量已满，请稍后重试")
    bus = EventBus(max_events=settings.event_buffer_max_events, max_buffer_bytes=settings.event_buffer_max_bytes,
                   max_event_bytes=settings.event_max_bytes, heartbeat_seconds=settings.event_heartbeat_seconds)
    runner = WorkflowRunner(request, bus, settings)
    task = asyncio.create_task(runner.run())
    _RUNNING[runner.run_id] = task

    async def stream():
        try:
            async for chunk in bus.drain():
                yield chunk
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001, S110 - run errors already emitted
                    pass
            if _RUNNING.get(runner.run_id) is task:
                _RUNNING.pop(runner.run_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/executions/{run_id}/cancel")
async def cancel(run_id: str, x_internal_token: str = Header(default="")):
    require_internal(x_internal_token)
    task = _RUNNING.get(run_id)
    if task is None or task.done():
        return {"data": {"cancelled": False}}
    task.cancel()
    return {"data": {"cancelled": True}}


@router.post("/executions/validate")
async def validate(request: ExecutionRequest):
    from app.graph.compiler import validate_flow

    validate_flow(request.flow)
    return {"data": {"valid": True}}
