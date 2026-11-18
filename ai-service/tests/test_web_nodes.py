import asyncio
import json

import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.mcp_client import McpServerConfig
from app.nodes import web_nodes
from app.nodes.web_nodes import WebFetchNodeExecutor, WebSearchNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context(**overrides) -> NodeContext:
    settings = Settings(java_service_base_url="http://java.test", internal_token="token",
                        tavily_api_key="tvly-test", tavily_base_url="https://api.tavily.test")
    return NodeContext(
        run_id="run-web",
        settings=settings,
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
        **overrides,
    )


def _run(executor, node, ctx, state=None):
    return asyncio.run(executor.execute(node, state or {}, ctx))


def test_web_fetch_collects_pages_and_failures(monkeypatch):
    calls = []

    async def fake_fetch(url, *, timeout_ms=15000, max_chars=8000):
        calls.append(url)
        if "bad" in url:
            raise web_nodes.WebFetchError("不允许访问内网地址")
        return {"url": url, "content": f"正文 {url}", "charCount": 5, "truncated": False, "contentType": "text/html"}

    monkeypatch.setattr(web_nodes, "fetch_public_text", fake_fetch)
    node = FlowNode(id="fetch", type="web_fetch",
                    config={"urls": "https://a.test/page\nhttps://bad.test/x", "maxChars": 1000})
    result = _run(WebFetchNodeExecutor(), node, _context())

    assert calls == ["https://a.test/page", "https://bad.test/x"]
    assert result["count"] == 1
    assert result["citations"] == ["https://a.test/page"]
    assert result["failures"][0]["url"] == "https://bad.test/x"
    assert "URL: https://a.test/page" in result["content"]


def test_web_fetch_raises_when_every_page_fails(monkeypatch):
    async def fake_fetch(url, **kwargs):
        raise web_nodes.WebFetchError("仅支持 http/https 公网地址")

    monkeypatch.setattr(web_nodes, "fetch_public_text", fake_fetch)
    node = FlowNode(id="fetch", type="web_fetch", config={"urls": "file:///etc/passwd"})
    with pytest.raises(NodeExecutionError):
        _run(WebFetchNodeExecutor(), node, _context())


def test_web_search_tavily_normalizes_results(monkeypatch):
    captured = {}

    async def fake_search(api_key, base_url, query, *, limit=5, freshness="", include_answer=True):
        captured.update(api_key=api_key, base_url=base_url, query=query,
                        limit=limit, freshness=freshness, include_answer=include_answer)
        return {
            "query": query,
            "answer": "简要结论",
            "results": [
                {"title": "结果一", "url": "https://one.test", "content": "内容一", "score": 0.9},
                {"title": "结果二", "link": "https://two.test", "snippet": "内容二"},
            ],
        }

    monkeypatch.setattr(web_nodes, "tavily_search", fake_search)
    node = FlowNode(id="search", type="web_search",
                    config={"provider": "tavily", "query": "LangGraph 是什么", "limit": 2, "freshness": "week"})
    result = _run(WebSearchNodeExecutor(), node, _context(), {"input": {}})

    assert captured["api_key"] == "tvly-test"
    assert captured["base_url"] == "https://api.tavily.test"
    assert captured["query"] == "LangGraph 是什么"
    assert captured["limit"] == 2
    assert captured["freshness"] == "week"
    assert result["summary"] == "简要结论"
    assert result["count"] == 2
    assert result["results"][1]["url"] == "https://two.test"
    assert result["citations"] == ["https://one.test", "https://two.test"]


def test_web_search_tavily_error_becomes_node_error(monkeypatch):
    async def fake_search(*args, **kwargs):
        raise web_nodes.WebSearchError("联网搜索失败: HTTP 401")

    monkeypatch.setattr(web_nodes, "tavily_search", fake_search)
    node = FlowNode(id="search", type="web_search", config={"provider": "tavily", "query": "x"})
    with pytest.raises(NodeExecutionError):
        _run(WebSearchNodeExecutor(), node, _context(), {"input": {}})


def test_web_search_requires_tavily_key(monkeypatch):
    ctx = _context()
    ctx.settings.tavily_api_key = ""
    monkeypatch.setattr(ctx, "credentials", lambda provider: ("", ""))
    node = FlowNode(id="search", type="web_search", config={"provider": "tavily", "query": "x"})
    with pytest.raises(NodeExecutionError):
        _run(WebSearchNodeExecutor(), node, ctx)


def test_web_search_mcp_uses_authorized_tool(monkeypatch):
    async def fake_call(server, tool, arguments, settings):
        assert tool == "web_search"
        assert arguments == {"query": "AgentFlow", "max_results": 3}
        return {"text": json.dumps({"results": [{"title": "A", "url": "https://a.test", "content": "B"}]}),
                "data": None}

    monkeypatch.setattr(web_nodes, "call_tool", fake_call)
    server = McpServerConfig(url="https://mcp.test/mcp", allowedTools=["web_search"])
    ctx = _context(mcp_servers={"s1": server})
    node = FlowNode(id="search", type="web_search", config={
        "provider": "mcp", "serverId": "s1", "toolName": "web_search",
        "arguments": '{"query":"AgentFlow","max_results":3}',
    })
    result = _run(WebSearchNodeExecutor(), node, ctx)
    assert result["provider"] == "mcp"
    assert result["query"] == "AgentFlow"
    assert result["results"][0]["url"] == "https://a.test"


def test_web_search_mcp_rejects_unauthorized_tool():
    server = McpServerConfig(url="https://mcp.test/mcp", allowedTools=["other"])
    ctx = _context(mcp_servers={"s1": server})
    node = FlowNode(id="search", type="web_search",
                    config={"provider": "mcp", "serverId": "s1", "toolName": "web_search"})
    with pytest.raises(NodeExecutionError):
        _run(WebSearchNodeExecutor(), node, ctx)
