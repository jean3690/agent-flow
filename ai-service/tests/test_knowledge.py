import asyncio
import json
import math

import httpx
import pytest

from app.api import embeddings as embeddings_api
from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes import knowledge_node
from app.nodes.knowledge_node import KnowledgeNodeExecutor, KnowledgeUpsertNodeExecutor
from app.schemas.flow import Flow, FlowNode


def test_embedding_endpoint_is_deterministic_in_mock_mode():
    request = embeddings_api.EmbeddingRequest(provider="mock", input=["你好世界", "第二个文本"])
    first = asyncio.run(embeddings_api.embeddings(request))["data"]
    second = asyncio.run(embeddings_api.embeddings(request))["data"]

    assert first["mock"] is True
    assert len(first["vectors"]) == 2
    assert first["vectors"] == second["vectors"]
    assert all(abs(math.sqrt(sum(value * value for value in vector)) - 1) < 0.01 for vector in first["vectors"])


def test_knowledge_node_requires_knowledge_base():
    ctx = NodeContext(
        run_id="run-knowledge",
        settings=Settings(mock_mode="auto"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
    )
    node = FlowNode(id="kb1", type="knowledge", config={})
    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(KnowledgeNodeExecutor().execute(node, {}, ctx))
    assert "知识库" in error.value.message


def _memory_context() -> NodeContext:
    return NodeContext(
        run_id="run-kb-write",
        settings=Settings(platform_service_base_url="http://java.test", internal_token="token"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
    )


def _mock_client(monkeypatch, handler):
    class _Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(knowledge_node.httpx, "AsyncClient", _Client)


def test_knowledge_upsert_sends_document_and_requires_indexed(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["token"] = request.headers.get("x-internal-token")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "data": {
            "id": 9, "title": "周报", "status": "INDEXED", "chunkCount": 2,
        }})

    _mock_client(monkeypatch, handler)
    node = FlowNode(id="kb-write", type="knowledge_upsert", config={
        "knowledgeBaseId": "5", "title": "第{{input.week}}周周报", "content": "{{input.body}}",
    })
    result = asyncio.run(KnowledgeUpsertNodeExecutor().execute(
        node, {"input": {"week": 3, "body": "本周完成记忆系统"}}, _memory_context()))

    assert captured["path"] == "/internal/knowledge/upsert"
    assert captured["token"] == "token"
    assert captured["body"]["knowledgeBaseId"] == "5"
    assert captured["body"]["title"] == "第3周周报"
    assert captured["body"]["content"] == "本周完成记忆系统"
    assert result["documentId"] == 9
    assert result["chunkCount"] == 2


def test_knowledge_upsert_failed_index_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {
            "id": 9, "title": "周报", "status": "FAILED", "errorMessage": "embedding 服务不可用",
        }})

    _mock_client(monkeypatch, handler)
    node = FlowNode(id="kb-write", type="knowledge_upsert", config={
        "knowledgeBaseId": "5", "title": "周报", "content": "内容",
    })
    with pytest.raises(NodeExecutionError) as error:
        asyncio.run(KnowledgeUpsertNodeExecutor().execute(node, {}, _memory_context()))
    assert "embedding" in error.value.message
