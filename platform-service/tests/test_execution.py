from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from app.services.execution import get_execution_service


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


class FakeAi:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.canceled: list[str] = []

    @contextmanager
    def open_execution(self, payload):
        yield FakeResponse(self._lines())

    def cancel_execution(self, run_id):
        self.canceled.append(run_id)

    def _lines(self):
        events = [
            ("run_started", {"runId": "r1", "nodeCount": 2}),
            ("node_started", {"nodeId": "in", "nodeType": "input", "nodeName": "输入", "seq": 1}),
            ("node_finished", {"nodeId": "in", "status": "success", "output": {"topic": "x"}, "elapsedMs": 1}),
            ("node_started", {"nodeId": "out", "nodeType": "output", "nodeName": "输出", "seq": 2}),
        ]
        if self.fail:
            events.append(
                ("node_failed", {"nodeId": "out", "error": {"message": "boom"}, "elapsedMs": 2})
            )
            events.append(
                ("run_failed", {"runId": "r1", "status": "failed", "error": {"message": "boom"}, "elapsedMs": 3})
            )
        else:
            events.append(
                (
                    "node_finished",
                    {
                        "nodeId": "out",
                        "status": "success",
                        "output": {
                            "result": {"topic": "x"},
                            "usage": {"promptTokens": 3, "completionTokens": 2, "totalTokens": 5},
                            "model": "agentflow-mock",
                        },
                        "elapsedMs": 2,
                    },
                )
            )
            events.append(
                (
                    "run_finished",
                    {"runId": "r1", "status": "success", "output": {"result": {"topic": "x"}}, "elapsedMs": 4},
                )
            )
        lines: list[str] = []
        for name, body in events:
            lines.extend([f"event: {name}", "data: " + json.dumps(body, ensure_ascii=False), ""])
        lines.extend(["event: done", "data: {}", ""])
        return lines


@pytest.fixture()
def fake_ai(monkeypatch):
    fake = FakeAi()
    monkeypatch.setattr(get_execution_service(), "ai", fake)
    return fake


def _create_flow(client, auth, name):
    flow = {
        "nodes": [
            {"id": "in", "type": "input", "config": {"variables": ["topic"]}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"source": "in", "target": "out"}],
    }
    response = client.post("/api/workflows", headers=auth, json={"name": name, "flow": flow})
    return response.json()["data"]["id"]


def test_sync_run_persists_record_and_nodes(client, auth, fake_ai):
    wid = _create_flow(client, auth, "同步执行")
    response = client.post(f"/api/workflows/{wid}/run", headers=auth, json={"input": {"topic": "x"}})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["totalTokens"] == 5
    assert data["costUsd"] == 0
    detail = client.get(f"/api/executions/{data['runId']}", headers=auth).json()["data"]
    assert len(detail["nodes"]) == 2
    assert detail["nodes"][0]["status"] == "SUCCESS"


def test_sse_run_streams_terminal_event(client, auth, fake_ai):
    wid = _create_flow(client, auth, "流式执行")
    response = client.post(f"/api/workflows/{wid}/execute", headers=auth, json={"input": {"topic": "x"}})
    assert response.status_code == 200
    assert "event: node_started" in response.text
    assert "event: run_finished" in response.text
    assert "event: done" in response.text


def test_resume_rejects_changed_input_and_accepts_same(client, auth, monkeypatch):
    execution = get_execution_service()
    monkeypatch.setattr(execution, "ai", FakeAi(fail=True))
    wid = _create_flow(client, auth, "续跑")
    failed = client.post(f"/api/workflows/{wid}/run", headers=auth, json={"input": {"topic": "x"}}).json()["data"]
    assert failed["status"] == "FAILED"
    run_id = failed["runId"]

    monkeypatch.setattr(execution, "ai", FakeAi())
    mismatch = client.post(
        f"/api/workflows/{wid}/run",
        headers=auth,
        json={"input": {"topic": "changed"}, "resumeRunId": run_id},
    )
    assert mismatch.status_code == 409
    assert "变化" in mismatch.json()["message"]

    resumed = client.post(
        f"/api/workflows/{wid}/run",
        headers=auth,
        json={"input": {"topic": "x"}, "resumeRunId": run_id},
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["status"] == "SUCCESS"


def test_execution_ownership_and_delete(client, auth, fake_ai):
    wid = _create_flow(client, auth, "执行归属")
    data = client.post(f"/api/workflows/{wid}/run", headers=auth, json={"input": {"topic": "x"}}).json()["data"]
    assert client.get(f"/api/executions/{data['runId']}", headers=auth).status_code == 200
    assert client.delete(f"/api/executions/{data['runId']}", headers=auth).status_code == 200
    assert client.get(f"/api/executions/{data['runId']}", headers=auth).status_code == 404
    assert client.delete("/api/executions/missing", headers=auth).status_code == 404


def test_invalid_timeout_is_rejected(client, auth, fake_ai):
    wid = _create_flow(client, auth, "超时参数")
    response = client.post(
        f"/api/workflows/{wid}/run", headers=auth, json={"input": {}, "timeoutMs": 0}
    )
    assert response.status_code == 400
    assert "timeoutMs" in response.json()["message"]
