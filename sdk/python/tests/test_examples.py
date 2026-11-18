import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from agentflow import AgentFlowClient

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/mcp_workflow.py"


def load_example():
    spec = importlib.util.spec_from_file_location("mcp_workflow_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def setup_example(monkeypatch, *, extra_args=(), probe=None, status="SUCCESS"):
    module = load_example()
    calls = []
    probe = probe if probe is not None else {"ok": True, "tools": [{"name": "echo"}]}

    def handler(request):
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, path, body))
        assert request.headers["X-API-Key"] == "af_platform"
        if path.endswith("/discover"):
            data = probe
        elif path == "/api/workflows":
            data = {"id": 9}
        elif path.endswith("/run"):
            data = {"status": status, "outputs": {"data": {"text": "hello"}}}
        else:
            data = {"id": 7, "name": "example", "url": "https://tools.example/mcp", "timeoutMs": 15000}
        return httpx.Response(200, json={"code": 0, "data": data})

    monkeypatch.setattr(module, "AgentFlowClient", lambda base_url, api_key: AgentFlowClient(
        base_url, api_key=api_key, transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("AGENTFLOW_API_KEY", "af_platform")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "REMOTE_SECRET")
    monkeypatch.setattr(sys, "argv", ["mcp_workflow.py", "--mcp-url", "https://tools.example/mcp", "--tool", "echo", *extra_args])
    return module, calls


def test_example_configures_without_invoking_tools_and_keeps_secrets_out_of_workflow(monkeypatch, capsys):
    module, calls = setup_example(monkeypatch)
    module.main()
    assert [(method, path) for method, path, _ in calls] == [
        ("POST", "/api/mcp-servers"), ("POST", "/api/mcp-servers/7/discover"),
        ("POST", "/api/workflows"), ("PUT", "/api/mcp-servers/7"),
    ]
    assert calls[0][2]["enabled"] is False and calls[0][2]["allowedTools"] == []
    assert calls[-1][2]["allowedTools"] == ["echo"] and calls[-1][2]["enabled"] is True
    assert "headers" not in calls[-1][2]
    assert "REMOTE_SECRET" not in json.dumps(calls[2][2])
    output = capsys.readouterr().out
    assert "No MCP tool was invoked" in output
    assert "af_platform" not in output and "REMOTE_SECRET" not in output


@pytest.mark.parametrize("probe", [
    {"ok": False, "tools": []}, {"ok": True, "tools": [{"name": "other"}]},
])
def test_example_does_not_enable_or_grant_when_probe_fails_or_tool_is_missing(monkeypatch, probe):
    module, calls = setup_example(monkeypatch, probe=probe)
    with pytest.raises(RuntimeError, match="remains disabled"):
        module.main()
    assert len(calls) == 2
    assert calls[0][2]["enabled"] is False


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED"])
def test_example_runs_only_with_explicit_flag_and_checks_workflow_status(monkeypatch, status):
    module, calls = setup_example(monkeypatch, extra_args=("--run",), status=status)
    if status == "FAILED":
        with pytest.raises(RuntimeError, match="did not succeed"):
            module.main()
    else:
        module.main()
    assert calls[-1][1] == "/api/workflows/9/run"


def test_example_invalid_json_inputs_fail_before_sending_any_request(monkeypatch):
    module, calls = setup_example(monkeypatch, extra_args=("--input", "[]"))
    with pytest.raises(SystemExit):
        module.main()
    assert calls == []


def test_example_flow_preserves_typed_templates_and_returns_full_tool_output():
    arguments = {"count": "{{input.count}}", "values": [0, False, None]}
    flow = load_example().workflow(7, "echo", arguments)
    assert json.loads(flow["nodes"][1]["config"]["arguments"]) == arguments
    assert flow["nodes"][1]["config"]["serverId"] == "7"
    assert flow["nodes"][-1]["config"] == {"mode": "key", "key": "outputs.tool"}
