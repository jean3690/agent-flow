import asyncio

import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.nodes.control_nodes import (
    DelayNodeExecutor,
    ForeachNodeExecutor,
    MergeNodeExecutor,
    SubflowNodeExecutor,
)
from app.schemas.flow import Flow, FlowNode


class RecordingBus:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.closed = False

    def emit(self, event, **data):
        self.events.append((event, data))

    def close(self):
        self.closed = True


def _ctx(tmp_path, *, flow=None, subflows=None, bus=None):
    return NodeContext(
        run_id="run-control",
        settings=Settings(mock_mode="always", file_dir=str(tmp_path), output_dir=str(tmp_path)),
        flow=flow or Flow(nodes=[], edges=[]),
        bus=bus or RecordingBus(),
        subflows=subflows or {},
    )


def _child_flow() -> Flow:
    return Flow.model_validate({
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "config": {"variables": ["item"]}},
            {"id": "tpl", "type": "template", "name": "模板", "config": {"template": "处理 {{input.item}}"}},
            {"id": "out", "type": "output", "name": "输出", "config": {}},
        ],
        "edges": [
            {"source": "in", "target": "tpl"},
            {"source": "tpl", "target": "out"},
        ],
    })


def test_delay_node_waits(tmp_path):
    ctx = _ctx(tmp_path)
    node = FlowNode(id="wait", type="delay", config={"durationMs": 30})
    result = asyncio.run(DelayNodeExecutor().execute(node, {"input": {}}, ctx))
    assert result["durationMs"] == 30
    assert result["elapsedMs"] >= 10


def test_merge_node_modes(tmp_path):
    outputs = {"a": {"text": "A"}, "b": {"text": "B"}}
    state = {"input": {}, "outputs": outputs}
    ctx = _ctx(tmp_path)

    def run(mode, **extra):
        node = FlowNode(id="merge", type="merge", config={"sources": ["a", "b"], "mode": mode, **extra})
        return asyncio.run(MergeNodeExecutor().execute(node, state, ctx))

    assert run("object")["value"] == {"a": "A", "b": "B"}
    assert run("array")["value"] == ["A", "B"]
    assert run("text", joinWith="|")["value"] == "A|B"
    assert run("first")["value"] == "A"


def test_merge_node_uses_incoming_edges_by_default(tmp_path):
    flow = Flow.model_validate({
        "nodes": [
            {"id": "a", "type": "template", "config": {}},
            {"id": "b", "type": "template", "config": {}},
            {"id": "merge", "type": "merge", "config": {}},
        ],
        "edges": [{"source": "a", "target": "merge"}, {"source": "b", "target": "merge"}],
    })
    ctx = _ctx(tmp_path, flow=flow)
    result = asyncio.run(
        MergeNodeExecutor().execute(
            FlowNode(id="merge", type="merge", config={}),
            {"input": {}, "outputs": {"a": {"text": "A"}, "b": {"text": "B"}}},
            ctx,
        )
    )
    assert result["value"] == {"a": "A", "b": "B"}


def test_subflow_node_runs_embedded_flow(tmp_path):
    ctx = _ctx(tmp_path, subflows={"11": _child_flow()})
    node = FlowNode(
        id="sub",
        type="subflow",
        config={"workflowId": "11", "input": '{"item": "{{input.topic}}"}'},
    )
    result = asyncio.run(
        SubflowNodeExecutor().execute(node, {"input": {"topic": "AgentFlow"}}, ctx)
    )
    assert result["text"] == "处理 AgentFlow"
    assert result["subflowId"] == "11"
    assert result["nodeCount"] == 3


def test_subflow_node_requires_embedded_definition(tmp_path):
    ctx = _ctx(tmp_path)
    node = FlowNode(id="sub", type="subflow", config={"workflowId": "404"})
    with pytest.raises(NodeExecutionError):
        asyncio.run(SubflowNodeExecutor().execute(node, {"input": {}}, ctx))


def test_foreach_node_runs_body_for_each_item(tmp_path):
    ctx = _ctx(tmp_path, subflows={"11": _child_flow()})
    node = FlowNode(
        id="loop",
        type="foreach",
        config={"items": "{{input.items}}", "bodyWorkflowId": "11", "concurrency": 2},
    )
    result = asyncio.run(
        ForeachNodeExecutor().execute(node, {"input": {"items": ["a", "b"]}}, ctx)
    )

    assert result["count"] == 2
    assert result["successCount"] == 2
    assert result["failedCount"] == 0
    assert [item["output"] for item in result["results"]] == ["处理 a", "处理 b"]
    assert result["results"][1]["index"] == 1


def test_foreach_rejects_non_array_items(tmp_path):
    ctx = _ctx(tmp_path, subflows={"11": _child_flow()})
    node = FlowNode(id="loop", type="foreach", config={"items": "not-a-list", "bodyWorkflowId": "11"})
    with pytest.raises(NodeExecutionError):
        asyncio.run(ForeachNodeExecutor().execute(node, {"input": {}}, ctx))


def test_runtime_retries_then_fails(tmp_path):
    bus = RecordingBus()
    ctx = _ctx(tmp_path, bus=bus)
    node = FlowNode(id="read", type="file_read", config={"path": "missing.txt", "retry": 2, "retryDelayMs": 0})

    with pytest.raises(NodeExecutionError):
        asyncio.run(execute_node(node, {"input": {}}, ctx))

    retries = [data for event, data in bus.events if event == "node_log" and "重试" in data.get("message", "")]
    assert len(retries) == 2
    assert sum(1 for event, _ in bus.events if event == "node_failed") == 1


def test_runtime_timeout_is_reported(tmp_path):
    ctx = _ctx(tmp_path)
    node = FlowNode(id="slow", type="delay", config={"durationMs": 200, "timeoutMs": 20})

    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(execute_node(node, {"input": {}}, ctx))

    assert "超时" in str(error.value)


def test_runtime_on_error_continue_marks_failed_output(tmp_path):
    ctx = _ctx(tmp_path)
    node = FlowNode(
        id="read",
        type="file_read",
        config={"path": "missing.txt", "onError": "continue"},
    )
    result = asyncio.run(execute_node(node, {"input": {}}, ctx))

    assert result["outputs"]["read"]["failed"] is True
    assert "不存在" in result["outputs"]["read"]["error"]["message"]
