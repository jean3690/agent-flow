import asyncio

from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes import llm_node
from app.nodes.llm_node import LlmNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context() -> NodeContext:
    return NodeContext(
        run_id="run-llm-memory",
        settings=Settings(mock_mode="always"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
    )


def test_llm_node_recalls_memory_by_prompt(monkeypatch):
    captured = {}

    async def fake_retrieve(ctx, *, scope, query, top_k=4, provider="mock", model=""):
        captured.update(scope=scope, query=query, top_k=top_k, provider=provider)
        return {"context": "- 用户喜欢简洁回答", "count": 1}

    monkeypatch.setattr(llm_node, "retrieve_memory", fake_retrieve)
    node = FlowNode(id="llm", type="llm", config={
        "provider": "openai", "model": "gpt-4o-mini",
        "prompt": "{{input.q}}", "memoryScope": "workflow",
        "memoryTopK": 2, "memoryProvider": "mock",
    })
    result = asyncio.run(LlmNodeExecutor().execute(node, {"input": {"q": "怎么排版"}}, _context()))

    assert captured == {"scope": "workflow", "query": "怎么排版", "top_k": 2, "provider": "mock"}
    assert result["mock"] is True
    assert result["text"]


def test_llm_node_memory_failure_does_not_block(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("java down")

    monkeypatch.setattr(llm_node, "retrieve_memory", boom)
    node = FlowNode(id="llm", type="llm", config={
        "provider": "openai", "prompt": "hi", "memoryScope": "user",
    })
    result = asyncio.run(LlmNodeExecutor().execute(node, {"input": {}}, _context()))
    assert result["text"]


def test_llm_node_without_memory_scope_skips_recall(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("不应调用记忆召回")

    monkeypatch.setattr(llm_node, "retrieve_memory", boom)
    node = FlowNode(id="llm", type="llm", config={"provider": "openai", "prompt": "hi"})
    result = asyncio.run(LlmNodeExecutor().execute(node, {"input": {}}, _context()))
    assert result["text"]
