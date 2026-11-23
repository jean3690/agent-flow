import asyncio

from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.schemas.execution import ExecutionRequest
from app.schemas.flow import Flow, FlowNode


def test_execution_request_parses_resume_cache():
    request = ExecutionRequest.model_validate(
        {"flow": {"nodes": [], "edges": []}, "resume": {"tpl": {"text": "cached"}}}
    )
    assert request.resume["tpl"] == {"text": "cached"}


def test_execute_node_reuses_cached_output_without_running():
    ctx = NodeContext(
        run_id="run-resume",
        settings=Settings(mock_mode="always"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        resume_cache={"tpl": {"text": "cached"}},
    )
    node = FlowNode(id="tpl", type="template", config={"template": "这条模板不应该被执行"})
    result = asyncio.run(execute_node(node, {"input": {}}, ctx))

    assert result["outputs"]["tpl"] == {"text": "cached"}
    assert node.id in ctx.executed


async def test_cached_output_emits_explicit_cache_hit_without_modifying_usage():
    cached = {"text": "old", "usage": {"totalTokens": 99}}
    bus = EventBus()
    ctx = NodeContext(run_id="r", settings=Settings(mock_mode="always"), flow=Flow(), bus=bus,
                      resume_cache={"t": cached})
    await execute_node(FlowNode(id="t", type="template"), {"input": {}}, ctx)
    bus.close()
    events = [chunk async for chunk in bus.drain()]
    assert any('"cacheHit": true' in chunk and "event: node_finished" in chunk for chunk in events)
    assert cached["usage"]["totalTokens"] == 99


async def test_empty_cache_output_is_reused_instead_of_reexecuting_side_effects():
    ctx = NodeContext(run_id="r", settings=Settings(mock_mode="always"), flow=Flow(), bus=EventBus(),
                      resume_cache={"t": {}})
    # An unknown node would fail if the executor were called.
    result = await execute_node(FlowNode(id="t", type="nonexistent"), {"input": {}}, ctx)
    assert result["outputs"]["t"] == {}


async def test_input_node_never_uses_a_supplied_cache():
    ctx = NodeContext(run_id="r", settings=Settings(mock_mode="always"), flow=Flow(), bus=EventBus(),
                      resume_cache={"in": {"value": "old"}})
    result = await execute_node(FlowNode(id="in", type="input"), {"input": {"topic": "fresh"}}, ctx)
    assert result["outputs"]["in"] != {"value": "old"}
    assert "fresh" in str(result["outputs"]["in"])
