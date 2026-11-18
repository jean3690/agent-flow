import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agentflow import AgentFlowClient, ApiError

SKILL = "---\nname: report-helper\ndescription: 中文报告\n---\n不编造事实。\n"


def test_mcp_lifecycle_preserves_fields_and_platform_auth():
    calls = []

    def handler(request):
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        assert request.headers["X-API-Key"] == "af_platform"
        assert "Authorization" not in request.headers
        if request.url.path.endswith("/discover"):
            data = {"ok": True, "tools": [{"name": "echo"}], "message": "connected"}
        else:
            data = {"id": 7}
        return httpx.Response(200, json={"code": 0, "data": data})

    with AgentFlowClient("http://test", api_key="af_platform", transport=httpx.MockTransport(handler)) as client:
        client.mcp.list()
        client.mcp.create("中文服务", "https://tools.example/mcp", headers={"Authorization": "Bearer REMOTE"}, enabled=False)
        assert client.mcp.discover(7)["ok"] is True
        client.mcp.update(7, name="中文服务", url="https://tools.example/mcp", allowed_tools=["echo"], timeout_ms=1000, enabled=False)
        client.mcp.tools(7)
        client.mcp.delete(7)

    assert [(method, path) for method, path, _ in calls] == [
        ("GET", "/api/mcp-servers"), ("POST", "/api/mcp-servers"),
        ("POST", "/api/mcp-servers/7/discover"), ("PUT", "/api/mcp-servers/7"),
        ("GET", "/api/mcp-servers/7/tools"), ("DELETE", "/api/mcp-servers/7"),
    ]
    assert calls[1][2]["headers"] == {"Authorization": "Bearer REMOTE"}
    assert calls[1][2]["allowedTools"] == [] and calls[1][2]["enabled"] is False
    assert calls[3][2] == {"name": "中文服务", "url": "https://tools.example/mcp", "allowedTools": ["echo"], "timeoutMs": 1000, "enabled": False, "clearHeaders": False}


def test_mcp_update_explicitly_clears_or_replaces_headers_without_mutating_input():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "data": {"id": 7}})

    with AgentFlowClient("http://test", token="JWT", transport=httpx.MockTransport(handler)) as client:
        fields = {"name": "server", "url": "https://tools.example/mcp", "allowed_tools": [], "timeout_ms": 15000, "enabled": True}
        client.mcp.update(7, **fields, clear_headers=True)
        headers = {"X-API-Key": "REMOTE"}
        client.mcp.update(7, **fields, headers=headers)
        assert headers == {"X-API-Key": "REMOTE"}
    assert calls[0]["clearHeaders"] is True and "headers" not in calls[0]
    assert calls[1]["headers"] == {"X-API-Key": "REMOTE"}


def test_mcp_full_update_does_not_supply_missing_settings():
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: pytest.fail("must not send incomplete update"))) as client:
        with pytest.raises(TypeError):
            client.mcp.update(7, name="server", url="https://tools.example/mcp")


@pytest.mark.parametrize("tools", ["echo", [1], [""]])
def test_mcp_update_cannot_turn_invalid_tool_lists_into_permissions(tools):
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: pytest.fail("invalid tool list reached network"))) as client:
        with pytest.raises((TypeError, ValueError)):
            client.mcp.update(7, name="server", url="https://tools.example/mcp", allowed_tools=tools, timeout_ms=15000, enabled=True)


@pytest.mark.parametrize("method,path,invoke", [
    ("GET", "/api/skills", lambda resource: resource.list()),
    ("GET", "/api/skills/report-helper", lambda resource: resource.get("report-helper")),
    ("PUT", "/api/skills/report-helper", lambda resource: resource.save("report-helper", SKILL)),
    ("DELETE", "/api/skills/report-helper", lambda resource: resource.delete("report-helper")),
    ("POST", "/api/skills/reload", lambda resource: resource.reload()),
    ("GET", "/api/skills/report-helper/references/guide.v1.md", lambda resource: resource.reference("report-helper", "guide.v1.md")),
])
def test_skill_methods_and_unicode_content(method, path, invoke):
    def handler(request):
        assert request.method == method and request.url.path == path
        assert request.headers["Authorization"] == "Bearer JWT"
        if method == "PUT":
            assert json.loads(request.content) == {"content": SKILL}
        return httpx.Response(200, json={"code": 0, "data": {"content": "中文资料"}})
    with AgentFlowClient("http://test", token="JWT", transport=httpx.MockTransport(handler)) as client:
        assert invoke(client.skills) == {"content": "中文资料"}


@pytest.mark.parametrize("identifier", ["../secret", "UPPER", "a/b", "", "x?token=y"])
def test_skill_identifiers_cannot_change_request_paths(identifier):
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: pytest.fail("invalid path reached network"))) as client:
        with pytest.raises(ValueError):
            client.skills.get(identifier)


@pytest.mark.parametrize("file", ["../guide.md", "folder/guide.md", "script.py"])
def test_reference_files_cannot_escape_the_reference_endpoint(file):
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: pytest.fail("invalid path reached network"))) as client:
        with pytest.raises(ValueError):
            client.skills.reference("report-helper", file)


@pytest.mark.parametrize("server_id", [0, -1, True, 1.5, "1"])
def test_mcp_ids_are_positive_integers(server_id):
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: pytest.fail("invalid id reached network"))) as client:
        with pytest.raises(ValueError):
            client.mcp.tools(server_id)


@pytest.mark.parametrize("status,code", [(403, 4030), (200, 4040)])
def test_integration_permission_errors_are_not_swallowed(status, code):
    response = lambda _: httpx.Response(status, json={"code": code, "message": "not allowed", "data": None})
    with AgentFlowClient("http://test", transport=httpx.MockTransport(response)) as client:
        with pytest.raises(ApiError) as error:
            client.skills.save("report-helper", SKILL)
        assert error.value.code == (status if status >= 400 else code)
        with pytest.raises(ApiError):
            client.mcp.tools(7)


def test_failed_mcp_probe_remains_a_typed_result_not_http_success_assumption():
    result = {"ok": False, "tools": [], "message": "connection failed"}
    with AgentFlowClient("http://test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 0, "data": result}))) as client:
        assert client.mcp.discover(7) == result
