import asyncio
import json

import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes import rag_nodes
from app.nodes.rag_nodes import (
    HydeRetrieveNodeExecutor,
    MultiQueryRetrieveNodeExecutor,
    RagAnswerNodeExecutor,
    RerankNodeExecutor,
)
from app.schemas.flow import Flow, FlowNode


def _context(mock: bool = True) -> NodeContext:
    return NodeContext(
        run_id="run-rag",
        settings=Settings(mock_mode="always" if mock else "never",
                          java_service_base_url="http://java.test", internal_token="token"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
    )


def _run(executor, node, state=None, ctx=None):
    return asyncio.run(executor.execute(node, state or {"input": {}}, ctx or _context()))


def _fake_search(monkeypatch, mapping, calls=None):
    async def fake(ctx, knowledge_base_id, query, top_k=4):
        if calls is not None:
            calls.append({"query": query, "topK": top_k, "kb": knowledge_base_id})
        for key, chunks in mapping.items():
            if key in query:
                return [dict(item) for item in chunks]
        return []

    monkeypatch.setattr(rag_nodes, "search_knowledge", fake)


def _fake_chat(monkeypatch, replies):
    queue = list(replies)

    async def fake(ctx, provider, model, system, user, **kwargs):
        if not queue:
            raise AssertionError("unexpected extra model call")
        return queue.pop(0), {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(rag_nodes, "_chat", fake)


def _chunk(chunk_id, content, title=""):
    return {"chunkId": chunk_id, "title": title, "content": content, "score": 0.5}


def test_multi_query_fuses_with_rrf(monkeypatch):
    calls = []
    _fake_search(monkeypatch, {
        "关键点": [_chunk(2, "退款条件"), _chunk(3, "其他说明")],
        "示例": [_chunk(2, "退款条件"), _chunk(1, "退款需要 3 天")],
        "退款": [_chunk(1, "退款需要 3 天"), _chunk(2, "退款条件")],
    }, calls)
    node = FlowNode(id="mq", type="multi_query_retrieve", config={
        "provider": "mock", "knowledgeBaseId": "5", "query": "退款多久到账",
        "numQueries": 3, "topK": 2, "finalTopK": 3,
    })
    result = _run(MultiQueryRetrieveNodeExecutor(), node)

    assert len(calls) == 3
    assert calls[0]["query"] == "退款多久到账"
    assert len(result["queries"]) == 3
    assert result["chunks"][0]["content"] == "退款条件"
    assert len(result["chunks"][0]["matchedQueries"]) >= 2
    assert result["count"] <= 3
    assert result["mock"] is True


def test_hyde_generates_hypothetical_and_searches(monkeypatch):
    calls = []
    _fake_search(monkeypatch, {"退款": [_chunk(1, "退款需要 3 天")]}, calls)
    _fake_chat(monkeypatch, ["假设性资料：退款一般在 3 个工作日内到账。"])
    node = FlowNode(id="hyde", type="hyde_retrieve", config={
        "provider": "openai", "knowledgeBaseId": "5", "query": "退款多久到账",
    })
    result = _run(HydeRetrieveNodeExecutor(), node, ctx=_context(mock=False))

    assert len(calls) == 2
    assert calls[0]["query"] == "退款多久到账"
    assert "3 个工作日" in calls[1]["query"]
    assert "3 个工作日" in result["hypothetical"]
    assert result["chunks"][0]["content"] == "退款需要 3 天"
    assert result["mock"] is False


def test_rerank_reorders_and_truncates(monkeypatch):
    _fake_chat(monkeypatch, ['[{"index":0,"score":2},{"index":1,"score":9}]'])
    source = json.dumps([_chunk(1, "弱相关"), _chunk(2, "强相关")], ensure_ascii=False)
    node = FlowNode(id="rerank", type="rerank", config={
        "provider": "openai", "query": "问题", "source": source, "topK": 1,
    })
    result = _run(RerankNodeExecutor(), node, ctx=_context(mock=False))

    assert result["inputCount"] == 2
    assert result["count"] == 1
    assert result["chunks"][0]["content"] == "强相关"
    assert result["chunks"][0]["rerankScore"] == 9.0


def test_rerank_mock_keeps_order(monkeypatch):
    source = json.dumps([_chunk(1, "A"), _chunk(2, "B")], ensure_ascii=False)
    node = FlowNode(id="rerank", type="rerank", config={
        "provider": "mock", "query": "q", "source": source, "topK": 2,
    })
    result = _run(RerankNodeExecutor(), node)
    assert [item["content"] for item in result["chunks"]] == ["A", "B"]
    assert result["mock"] is True


def test_rerank_requires_chunks():
    node = FlowNode(id="rerank", type="rerank", config={"provider": "mock", "query": "q"})
    with pytest.raises(NodeExecutionError):
        _run(RerankNodeExecutor(), node)


def test_rag_answer_maps_citations(monkeypatch):
    _fake_chat(monkeypatch, ["退款需要 3 天 [2]，超时不支持 [1]。"])
    source = json.dumps([_chunk(1, "超时不支持退款"), _chunk(2, "退款 3 天到账", "退款政策")],
                        ensure_ascii=False)
    node = FlowNode(id="answer", type="rag_answer", config={
        "provider": "openai", "query": "退款多久", "source": source, "requireCitations": True,
    })
    result = _run(RagAnswerNodeExecutor(), node, ctx=_context(mock=False))

    assert result["cited"] is True
    assert [item["index"] for item in result["citations"]] == [1, 2]
    assert result["citations"][1]["title"] == "退款政策"
    assert result["chunks"][1]["content"] == "退款 3 天到账"


def test_rag_answer_mock_returns_citations():
    source = json.dumps([_chunk(1, "片段一"), _chunk(2, "片段二")], ensure_ascii=False)
    node = FlowNode(id="answer", type="rag_answer", config={
        "provider": "mock", "query": "q", "source": source,
    })
    result = _run(RagAnswerNodeExecutor(), node)
    assert result["mock"] is True
    assert len(result["citations"]) == 2
    assert result["text"].startswith("[mock")


def test_rag_answer_requires_chunks():
    node = FlowNode(id="answer", type="rag_answer", config={"provider": "mock", "query": "q"})
    with pytest.raises(NodeExecutionError):
        _run(RagAnswerNodeExecutor(), node)
