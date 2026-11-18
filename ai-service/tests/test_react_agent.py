import asyncio
import json

from app.agent_tools import _blocked_reason, execute_tool
from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.nodes.react_agent_node import ReactAgentNodeExecutor
from app.schemas.flow import Flow, FlowNode


def _context() -> NodeContext:
    return NodeContext(
        run_id="run-agent",
        settings=Settings(mock_mode="always"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
    )


def test_read_input_tool_returns_json():
    result = asyncio.run(execute_tool("read_input", {}, {"input": {"topic": "hi"}}, _context(), {}))
    assert json.loads(result) == {"topic": "hi"}


def test_web_fetch_blocks_private_hosts():
    result = asyncio.run(execute_tool("web_fetch", {"url": "http://127.0.0.1:8000/health"}, {}, _context(), {}))
    assert result.startswith("错误")
    assert _blocked_reason("localhost") == "不允许访问内网地址"
    assert _blocked_reason("127.0.0.1") == "不允许访问内网地址"


def test_web_search_tool_formats_results(monkeypatch):
    async def fake_search(api_key, base_url, query, **kwargs):
        assert query == "LangGraph"
        assert api_key == "tvly-test"
        return {"answer": "搜索摘要", "results": [
            {"title": "结果一", "url": "https://a.test", "content": "内容一"},
        ]}

    monkeypatch.setattr("app.agent_tools.tavily_search", fake_search)
    ctx = _context()
    ctx.settings.tavily_api_key = "tvly-test"
    result = asyncio.run(execute_tool("web_search", {"query": "LangGraph", "limit": 3}, {}, ctx, {}))
    assert "搜索摘要" in result
    assert "https://a.test" in result
    assert "内容一" in result


def test_web_search_tool_without_key_returns_error(monkeypatch):
    ctx = _context()
    monkeypatch.setattr(ctx, "credentials", lambda provider: ("", ""))
    result = asyncio.run(execute_tool("web_search", {"query": "x"}, {}, ctx, {}))
    assert result.startswith("错误")
    assert "Tavily" in result


def test_load_skill_tool_returns_content():
    result = asyncio.run(execute_tool("load_skill", {"name": "summarize"}, {}, _context(), {}))
    assert not result.startswith("错误")
    assert len(result) > 10


def test_react_agent_mock_returns_summary():
    node = FlowNode(id="agent", type="react_agent", config={"toolIds": ["read_input"], "prompt": "{{input}}"})
    result = asyncio.run(ReactAgentNodeExecutor().execute(node, {"input": {"topic": "x"}}, _context()))
    assert result["mock"] is True
    assert result["provider"] == "mock"
    assert "模拟" in result["text"]
