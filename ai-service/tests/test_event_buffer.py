import asyncio

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.core.events import EventBufferOverflow, EventBus
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.graph.runner import WorkflowRunner
from app.schemas.execution import ExecutionRequest
from app.schemas.execution import ExecutionOptions
from app.schemas.flow import Flow, FlowNode


async def collect(bus):
    return [chunk async for chunk in bus.drain()]


async def test_count_overflow_preserves_progress_and_emits_failure_then_done():
    bus = EventBus(max_events=1)
    bus.emit("node_started", runId="r", nodeId="n")
    with pytest.raises(EventBufferOverflow):
        bus.emit("node_token", runId="r", nodeId="n", text="not silently dropped")
    assert bus.closed
    bus.emit("run_finished", output="false success")
    bus.close()
    events = await asyncio.wait_for(collect(bus), 1)
    assert len(events) == 3
    assert events[0].startswith("event: node_started")
    assert events[1].startswith("event: run_failed") and "EVENT_BUFFER_OVERFLOW" in events[1]
    assert events[2].startswith("event: done")
    assert not any("run_finished" in event for event in events)
    assert bus.buffered_bytes == bus.buffered_events == 0


async def test_byte_budget_counts_utf8_bytes_not_character_count():
    bus = EventBus(max_events=100, max_buffer_bytes=256, max_event_bytes=1024)
    with pytest.raises(EventBufferOverflow):
        bus.emit("node_token", text="中" * 100)
    events = await collect(bus)
    assert "EVENT_BUFFER_OVERFLOW" in events[0]
    assert len(events) == 2


async def test_oversized_terminal_output_becomes_failure_not_success():
    bus = EventBus(max_event_bytes=256)
    with pytest.raises(EventBufferOverflow):
        bus.emit("run_finished", output="x" * 1000)
    events = await collect(bus)
    assert "EVENT_TOO_LARGE" in events[0]
    assert all("event: run_finished" not in event for event in events)


async def test_terminal_and_close_have_reserved_capacity_when_normal_buffer_is_full():
    bus = EventBus(max_events=1)
    bus.emit("node_finished", nodeId="n", output={})
    bus.emit("run_finished", output="ok")
    bus.emit("node_token", text="late and ignored after terminal")
    bus.emit("done", ignored_large_payload="x" * 10_000)
    bus.emit("done")
    bus.close()
    bus.close()
    events = await asyncio.wait_for(collect(bus), 1)
    assert [event.split("\n")[0] for event in events] == ["event: node_finished", "event: run_finished", "event: done"]
    assert bus.buffered_bytes == 0


async def test_consuming_progress_frees_capacity_for_the_producer():
    bus = EventBus(max_events=1)
    bus.emit("node_token", text="first")
    stream = bus.drain()
    assert "first" in await anext(stream)
    assert bus.buffered_events == 0
    bus.emit("node_token", text="second")
    assert "second" in await anext(stream)
    bus.close()
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_idle_stream_uses_comments_without_spending_queue_capacity():
    bus = EventBus(heartbeat_seconds=0.01)
    stream = bus.drain()
    assert await asyncio.wait_for(anext(stream), 1) == ": keep-alive\n\n"
    assert bus.buffered_bytes == bus.buffered_events == 0
    bus.emit("run_failed", error={"code": "TEST"})
    bus.close()
    assert "run_failed" in await anext(stream)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def test_overflow_cannot_be_swallowed_by_node_retry_or_continue(monkeypatch):
    calls = 0

    class Executor:
        async def execute(self, node, state, ctx):
            nonlocal calls
            calls += 1
            ctx.emit("node_token", nodeId=node.id, text="overflow")
            return {}

    monkeypatch.setattr("app.graph.runtime.get_executor", lambda _: Executor())
    bus = EventBus(max_events=1)
    node = FlowNode(id="n", type="custom", config={"retry": 5, "onError": "continue"})
    ctx = NodeContext(run_id="r", settings=Settings(), flow=Flow(nodes=[node]), bus=bus)
    with pytest.raises(EventBufferOverflow):
        await execute_node(node, {"input": {}}, ctx)
    assert calls == 1
    events = await collect(bus)
    assert "EVENT_BUFFER_OVERFLOW" in events[1]


@pytest.mark.parametrize("value", [0, -1, 3_600_001])
def test_execution_timeout_bounds_are_enforced(value):
    with pytest.raises(ValidationError):
        ExecutionOptions(timeoutMs=value)


@pytest.mark.parametrize("config", [
    {"max_concurrency": 0}, {"event_buffer_max_events": 0},
    {"event_buffer_max_bytes": 0}, {"event_max_bytes": 0}, {"event_heartbeat_seconds": 0},
])
def test_invalid_buffer_configuration_fails_validation(config):
    with pytest.raises(ValidationError):
        Settings(**config)


async def test_subsecond_runtime_timeout_is_honored(monkeypatch):
    class Graph:
        async def ainvoke(self, *_args, **_kwargs):
            await asyncio.Event().wait()

    monkeypatch.setattr("app.graph.runner.build_graph", lambda *_: Graph())
    bus = EventBus()
    request = ExecutionRequest(flow={"nodes": [{"id": "in", "type": "input"}], "edges": []},
                               options={"timeoutMs": 20})
    await asyncio.wait_for(WorkflowRunner(request, bus, Settings()).run(), 0.5)
    events = await collect(bus)
    assert "RUN_TIMEOUT" in events[1]
    assert events[-1].startswith("event: done")


async def test_oversized_run_id_cannot_make_the_reserved_failure_event_unbounded():
    bus = EventBus(max_event_bytes=256)
    with pytest.raises(EventBufferOverflow):
        bus.emit("run_started", runId="x" * 10_000)
    events = await collect(bus)
    assert len(events[0].encode("utf-8")) < 1024
    assert "EVENT_TOO_LARGE" in events[0]
