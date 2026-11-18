import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes import memory_nodes
from app.nodes.memory_nodes import MemoryRetrieveNodeExecutor, MemoryWriteNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context(workflow_id="42", user_id=7) -> NodeContext:
    return NodeContext(
        run_id="run-memory",
        settings=Settings(java_service_base_url="http://java.test", internal_token="token"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id=workflow_id,
        user_id=user_id,
    )


def _mock_client(monkeypatch, handler):
    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(memory_nodes.httpx, "AsyncClient", _Client)


def test_memory_write_sends_scope_and_returns_id(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["token"] = request.headers.get("x-internal-token")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "data": {"memoryId": "12", "scope": "workflow", "stored": True}})

    _mock_client(monkeypatch, handler)
    node = FlowNode(id="mem-write", type="memory_write", config={
        "scope": "workflow", "memoryType": "preference",
        "content": "用户偏好简洁回答：{{input.topic}}", "tags": ["偏好", "风格"],
        "provider": "mock", "model": "text-embedding-3-small",
    })
    result = asyncio.run(MemoryWriteNodeExecutor().execute(node, {"input": {"topic": "周报"}}, _context()))

    assert captured["path"] == "/internal/memory/write"
    assert captured["token"] == "token"
    assert captured["body"]["workflowId"] == 42
    assert captured["body"]["userId"] == 7
    assert captured["body"]["content"] == "用户偏好简洁回答：周报"
    assert captured["body"]["tags"] == ["偏好", "风格"]
    assert captured["body"]["sourceNodeId"] == "mem-write"
    assert result["memoryId"] == "12"
    assert result["stored"] is True
    assert result["memoryType"] == "preference"


def test_memory_retrieve_passes_topk_and_returns_context(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "data": {
            "memories": [{"memoryId": "1", "content": "用户喜欢表格", "score": 0.8}],
            "context": "- 用户喜欢表格",
            "count": 1,
        }})

    _mock_client(monkeypatch, handler)
    node = FlowNode(id="mem-read", type="memory_retrieve", config={
        "scope": "user", "query": "{{input.question}}", "topK": 3, "tags": "偏好",
    })
    result = asyncio.run(MemoryRetrieveNodeExecutor().execute(node, {"input": {"question": "怎么排版"}}, _context()))

    assert captured["body"]["scope"] == "user"
    assert captured["body"]["query"] == "怎么排版"
    assert captured["body"]["topK"] == 3
    assert captured["body"]["tags"] == ["偏好"]
    assert result["count"] == 1
    assert result["text"] == "- 用户喜欢表格"
    assert result["citations"] == ["1"]


def test_memory_workflow_scope_requires_workflow_id():
    node = FlowNode(id="mem-read", type="memory_retrieve", config={"scope": "workflow", "query": "x"})
    with pytest.raises(NodeExecutionError):
        asyncio.run(MemoryRetrieveNodeExecutor().execute(node, {}, _context(workflow_id=None)))


def test_memory_user_scope_requires_user_id():
    node = FlowNode(id="mem-write", type="memory_write", config={"scope": "user", "content": "x"})
    with pytest.raises(NodeExecutionError):
        asyncio.run(MemoryWriteNodeExecutor().execute(node, {}, _context(user_id=None)))


def test_memory_write_rejects_empty_content():
    node = FlowNode(id="mem-write", type="memory_write", config={"scope": "workflow", "content": "  "})
    with pytest.raises(NodeExecutionError):
        asyncio.run(MemoryWriteNodeExecutor().execute(node, {}, _context()))


def test_memory_node_wraps_java_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    _mock_client(monkeypatch, handler)
    node = FlowNode(id="mem-read", type="memory_retrieve", config={"scope": "workflow", "query": "x"})
    with pytest.raises(NodeExecutionError) as exc:
        asyncio.run(MemoryRetrieveNodeExecutor().execute(node, {}, _context()))
    assert "召回记忆失败" in str(exc.value)
