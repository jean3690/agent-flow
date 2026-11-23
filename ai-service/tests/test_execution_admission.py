import asyncio

import pytest
from fastapi import HTTPException

from app.api import executions
from app.config import Settings, get_settings
from app.schemas.execution import ExecutionRequest


def request(run_id):
    return ExecutionRequest(runId=run_id, flow={"nodes": [{"id": "in", "type": "input"}], "edges": []})


async def execute(payload):
    return await executions.execute(payload, x_internal_token=get_settings().internal_token)


async def test_capacity_rejects_without_starting_another_runner_and_recovers_after_drain(monkeypatch):
    monkeypatch.setattr(executions, "_RUNNING", {})
    monkeypatch.setattr(executions, "get_settings", lambda: Settings(max_concurrency=1))
    first = await execute(request("first"))
    with pytest.raises(HTTPException) as rejected:
        await execute(request("second"))
    assert rejected.value.status_code == 503
    assert list(executions._RUNNING) == ["first"]
    chunks = [chunk async for chunk in first.body_iterator]
    assert any("run_finished" in chunk for chunk in chunks)
    assert executions._RUNNING == {}
    second = await execute(request("second"))
    _ = [chunk async for chunk in second.body_iterator]
    assert executions._RUNNING == {}


async def test_duplicate_run_id_does_not_replace_the_cancellation_handle(monkeypatch):
    monkeypatch.setattr(executions, "_RUNNING", {})
    first = await execute(request("same"))
    original = executions._RUNNING["same"]
    with pytest.raises(HTTPException) as rejected:
        await execute(request("same"))
    assert rejected.value.status_code == 409
    assert executions._RUNNING["same"] is original
    _ = [chunk async for chunk in first.body_iterator]


async def test_closing_an_active_stream_cancels_the_runner_and_releases_admission(monkeypatch):
    monkeypatch.setattr(executions, "_RUNNING", {})
    gate = asyncio.Event()

    async def blocked_run(self):
        self.bus.emit("run_started", runId=self.run_id)
        try:
            await gate.wait()
        finally:
            self.bus.close()

    monkeypatch.setattr(executions.WorkflowRunner, "run", blocked_run)
    response = await execute(request("blocked"))
    producer = executions._RUNNING["blocked"]
    assert "run_started" in await anext(response.body_iterator)
    await response.body_iterator.aclose()
    assert producer.cancelled()
    assert executions._RUNNING == {}


async def test_buffer_exhaustion_releases_admission_and_never_emits_success(monkeypatch):
    monkeypatch.setattr(executions, "_RUNNING", {})
    monkeypatch.setattr(executions, "get_settings", lambda: Settings(max_concurrency=1, event_buffer_max_events=1))

    async def overflowing_run(self):
        try:
            self.bus.emit("run_started", runId=self.run_id)
            self.bus.emit("node_started", runId=self.run_id, nodeId="in")
        finally:
            self.bus.close()

    monkeypatch.setattr(executions.WorkflowRunner, "run", overflowing_run)
    response = await execute(request("overflow"))
    producer = executions._RUNNING["overflow"]
    chunks = [chunk async for chunk in response.body_iterator]
    assert producer.cancelled()
    assert any("EVENT_BUFFER_OVERFLOW" in chunk for chunk in chunks)
    assert not any("run_finished" in chunk for chunk in chunks)
    assert executions._RUNNING == {}
