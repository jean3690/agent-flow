import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from app import mcp_client
from app.api import skills as skill_routes
from app.config import Settings
from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.main import app
from app.mcp_client import McpServerConfig, call_tool, discover_tools, validate_target
from app.nodes.mcp_node import McpToolNodeExecutor
from app.nodes.react_agent_node import ReactAgentNodeExecutor
from app.schemas.flow import Flow, FlowNode
from app.skills.registry import SkillRegistry

CONTENT = "---\nname: test-skill\ntitle: 测试技能\ndescription: 为测试提供指令\ntags: [测试]\n---\n\n不编造事实。\n"


def test_skill_save_reload_delete_preserves_builtin(tmp_path):
    builtin, managed = tmp_path / "builtin", tmp_path / "managed"
    folder = builtin / "test-skill"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(CONTENT)
    registry = SkillRegistry(builtin, managed)
    assert registry.detail("test-skill")["editable"] is False
    with pytest.raises(ValueError, match="只读"):
        registry.save("test-skill", CONTENT)
    raw = CONTENT.replace("test-skill", "custom-skill")
    assert registry.save("custom-skill", raw)["rawContent"] == raw
    registry.reload()
    assert registry.detail("custom-skill")["editable"] is True
    registry.delete("custom-skill")
    assert registry.names() == ["test-skill"]
    assert (folder / "SKILL.md").read_text() == CONTENT


@pytest.mark.parametrize("name,content", [
    ("../escape", CONTENT), ("TEST", CONTENT), ("test-skill", "plain text"),
    ("other", CONTENT), ("test-skill", CONTENT.replace("tags: [测试]", "tags: wrong")),
    ("test-skill", CONTENT.replace("description: 为测试提供指令", "description: ''")),
    ("test-skill", CONTENT + "x" * 200000),
])
def test_skill_rejects_bad_names_content_or_metadata(tmp_path, name, content):
    registry = SkillRegistry(tmp_path / "builtin", tmp_path / "managed")
    with pytest.raises((ValueError, TypeError)):
        registry.save(name, content)


def test_skill_writer_rejects_symlink_folder(tmp_path):
    managed = tmp_path / "managed"
    managed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (managed / "test-skill").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        SkillRegistry(tmp_path / "builtin", managed).save("test-skill", CONTENT)
    assert not (outside / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_skill_management_requires_internal_auth_and_sanitizes_validation(tmp_path, monkeypatch):
    registry = SkillRegistry(tmp_path / "builtin", tmp_path / "managed")
    monkeypatch.setattr(skill_routes, "get_skill_registry", lambda: registry)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.put("/v1/skills/test-skill", json={"content": CONTENT})).status_code == 403
        from app.config import get_settings
        headers = {"X-Internal-Token": get_settings().internal_token}
        response = await client.put("/v1/skills/test-skill", json={"content": CONTENT}, headers=headers)
        assert response.status_code == 200
        assert (await client.delete("/v1/skills/test-skill", headers=headers)).status_code == 200
        response = await client.post("/v1/mcp/discover", json={"url": "https://mcp.example/mcp", "headers": {"Host": "SECRET"}}, headers=headers)
        assert response.status_code == 422 and "SECRET" not in response.text


@pytest.mark.parametrize("payload", [
    {"url": "file:///etc/passwd"}, {"url": "https://user:secret@example.com/mcp"},
    {"url": "https://example.com/mcp?token=secret"}, {"url": "https://example.com/mcp", "headers": {"Host": "evil"}},
    {"url": "https://example.com/mcp", "headers": {"Authorization": "a\r\nb"}},
    {"url": "https://example.com/mcp", "command": "bash"},
])
def test_mcp_rejects_unsupported_transports_and_unsafe_headers(payload):
    with pytest.raises(ValidationError):
        McpServerConfig.model_validate(payload)


@pytest.mark.asyncio
async def test_mcp_denies_private_addresses_and_allows_explicit_deployment_exception():
    with pytest.raises(ValueError, match="禁止内网"):
        await validate_target("http://127.0.0.1:8000/mcp", Settings())
    await validate_target("http://127.0.0.1:8000/mcp", Settings(mcp_private_hosts="127.0.0.1"))


@pytest.mark.asyncio
async def test_mcp_checks_every_dns_answer(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443)), (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.1.1.1", 443))])
    with pytest.raises(ValueError, match="禁止内网"):
        await validate_target("https://mixed.example/mcp", Settings())


@pytest.mark.asyncio
async def test_mcp_allowlist_checked_before_network(monkeypatch):
    connect = AsyncMock()
    monkeypatch.setattr(mcp_client, "validate_target", connect)
    with pytest.raises(ValueError, match="未授权"):
        await call_tool(McpServerConfig(url="https://example.com/mcp"), "write", {}, Settings())
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_real_mcp_http_discovery_and_typed_call(monkeypatch):
    server = FastMCP("AgentFlow Test", stateless_http=True, json_response=True)

    @server.tool()
    def echo(text: str, count: int = 1) -> dict[str, str | int]:
        """Echo typed arguments."""
        return {"text": text, "count": count}

    asgi = server.streamable_http_app()
    monkeypatch.setattr(mcp_client, "make_http_client", lambda config, guard: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=asgi), headers=config.headers, event_hooks={"request": [guard]},
    ))
    config = McpServerConfig(url="http://127.0.0.1:8123/mcp", allowedTools=["echo"])
    settings = Settings(mcp_private_hosts="127.0.0.1")
    async with server.session_manager.run():
        tools = await discover_tools(config, settings)
        assert tools[0]["name"] == "echo" and tools[0]["inputSchema"]["properties"]["count"]["type"] == "integer"
        result = await call_tool(config, "echo", {"text": "中文", "count": 0}, settings)
        assert result["data"] == {"text": "中文", "count": 0}


@pytest.mark.asyncio
async def test_mcp_node_renders_typed_arguments_and_scrubs_remote_error(monkeypatch):
    config = McpServerConfig(url="https://example.com/mcp", allowedTools=["echo"])
    ctx = NodeContext("run", Settings(), Flow(), type("Bus", (), {"emit": lambda *a, **kw: None})(), mcp_servers={"1": config})
    node = FlowNode(id="mcp", type="mcp_tool", config={"serverId": "1", "toolName": "echo", "arguments": '{"count":"{{input.count}}"}'})
    call = AsyncMock(return_value={"text": "ok", "data": {"ok": True}, "content": []})
    monkeypatch.setattr("app.nodes.mcp_node.call_tool", call)
    assert (await McpToolNodeExecutor().execute(node, {"input": {"count": 0}}, ctx))["text"] == "ok"
    assert call.await_args.args[2] == {"count": 0}
    call.side_effect = RuntimeError("Authorization Bearer SECRET")
    with pytest.raises(NodeExecutionError) as error:
        await McpToolNodeExecutor().execute(node, {"input": {"count": 0}}, ctx)
    assert "SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_agent_mock_does_not_connect_to_mcp(monkeypatch):
    discover = AsyncMock()
    monkeypatch.setattr("app.nodes.react_agent_node.discover_tools", discover)
    ctx = NodeContext("run", Settings(mock_mode="always"), Flow(), type("Bus", (), {"emit": lambda *a, **kw: None})())
    node = FlowNode(id="agent", type="react_agent", config={"provider": "mock", "mcpServerIds": ["1"]})
    result = await ReactAgentNodeExecutor().execute(node, {"input": {}}, ctx)
    assert "不连接远程" in result["text"]
    discover.assert_not_called()


@pytest.mark.asyncio
async def test_agent_binds_only_approved_mcp_tools_and_loads_skill_instructions(monkeypatch):
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

    class Model:
        def __init__(self):
            self.schemas = []
            self.calls = 0

        def bind_tools(self, schemas):
            self.schemas = schemas
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            assert any(isinstance(item, SystemMessage) and "技能约束" in item.content for item in messages)
            if self.calls == 1:
                name = next(item["function"]["name"] for item in self.schemas if item["function"]["name"].startswith("mcp_"))
                return AIMessage(content="", tool_calls=[{"name": name, "args": {"text": "任务"}, "id": "1", "type": "tool_call"}])
            assert any(isinstance(item, ToolMessage) and "工具结果" in item.content for item in messages)
            return AIMessage(content="完成")

    model = Model()
    monkeypatch.setattr("app.nodes.react_agent_node.build_chat_model", lambda *a, **kw: model)
    monkeypatch.setattr("app.nodes.react_agent_node.get_skill_registry", lambda: type("Registry", (), {"detail": lambda _, name: {"title": "测试", "content": "技能约束"}})())
    monkeypatch.setattr("app.nodes.react_agent_node.discover_tools", AsyncMock(return_value=[
        {"name": "echo", "description": "回声", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "delete", "description": "危险操作", "inputSchema": {"type": "object", "properties": {}}},
    ]))
    call = AsyncMock(return_value={"text": "工具结果", "data": None, "content": []})
    monkeypatch.setattr("app.nodes.react_agent_node.call_tool", call)
    config = McpServerConfig(url="https://example.com/mcp", allowedTools=["echo"])
    ctx = NodeContext("run", Settings(mock_mode="never"), Flow(), type("Bus", (), {"emit": lambda *a, **kw: None})(), mcp_servers={"1": config})
    node = FlowNode(id="agent", type="react_agent", config={"provider": "openai", "mcpServerIds": ["1"], "skillIds": ["test"]})
    result = await ReactAgentNodeExecutor().execute(node, {"input": {}}, ctx)
    assert result["text"] == "完成" and result["toolCalls"] == 1
    assert call.await_args.args[1] == "echo"
    assert len([schema for schema in model.schemas if schema["function"]["name"].startswith("mcp_")]) == 1
