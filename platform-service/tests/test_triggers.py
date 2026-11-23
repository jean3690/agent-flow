from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.database import session_scope
from app.errors import BizError
from app.services import triggers


def _workflow(client, auth, name="触发器工作流"):
    flow = {
        "nodes": [{"id": "in", "type": "input", "config": {}}, {"id": "out", "type": "output", "config": {}}],
        "edges": [{"source": "in", "target": "out"}],
    }
    return client.post("/api/workflows", headers=auth, json={"name": name, "flow": flow}).json()["data"]["id"]


def test_cron_validation_and_next_run():
    assert triggers.validate_cron("0 9 * * *") == "0 0 9 * * *"
    assert triggers.validate_cron("0 0 9 * * *") == "0 0 9 * * *"
    with pytest.raises(BizError):
        triggers.validate_cron("")
    with pytest.raises(BizError):
        triggers.validate_cron("* * *")
    nxt = triggers.next_run("0 0 9 * * *", "Asia/Shanghai")
    assert isinstance(nxt, datetime) and nxt.tzinfo is None


def test_trigger_crud_and_webhook(client, auth, monkeypatch):
    wid = _workflow(client, auth)
    created = client.post(
        f"/api/workflows/{wid}/triggers",
        headers=auth,
        json={"name": "hook", "type": "WEBHOOK", "input": {"static": 1}},
    )
    assert created.status_code == 200
    trigger = created.json()["data"]
    assert trigger["webhookPath"].startswith("/api/triggers/webhook/")

    class StubExecution:
        def submit(self, workflow_id, request, user_id, prefer_published, on_finish):
            on_finish({"runId": "run-1", "status": "SUCCESS"})
            return "run-1"

    monkeypatch.setattr("app.services.execution.get_execution_service", lambda: StubExecution())
    response = client.post(trigger["webhookPath"], json={"dynamic": 2})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ACCEPTED"

    listed = client.get(f"/api/workflows/{wid}/triggers", headers=auth).json()["data"]
    item = next(entry for entry in listed if entry["id"] == trigger["id"])
    assert item["lastRunId"] == "run-1"
    assert item["lastStatus"] == "SUCCESS"
    assert item["input"] == {"static": 1}

    rotated = client.post(f"/api/triggers/{trigger['id']}/rotate-token", headers=auth).json()["data"]
    assert rotated["webhookPath"] != trigger["webhookPath"]
    assert client.delete(f"/api/triggers/{trigger['id']}", headers=auth).status_code == 200


def test_cron_trigger_sets_next_run_and_rejects_invalid(client, auth):
    wid = _workflow(client, auth, "cron 工作流")
    created = client.post(
        f"/api/workflows/{wid}/triggers",
        headers=auth,
        json={"name": "daily", "type": "CRON", "cronExpression": "0 9 * * *", "timezone": "Asia/Shanghai"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["nextRunAt"]
    invalid = client.post(
        f"/api/workflows/{wid}/triggers",
        headers=auth,
        json={"name": "bad", "type": "CRON", "cronExpression": "not-a-cron"},
    )
    assert invalid.status_code == 400


def test_scheduler_lock_lease():
    from app.models import SchedulerLock

    with session_scope() as session:
        assert triggers._try_acquire_lock(session, "unit-lock", timedelta(seconds=10))
    with session_scope() as session:
        assert not triggers._try_acquire_lock(session, "unit-lock", timedelta(seconds=10))
        row = session.get(SchedulerLock, "unit-lock")
        row.expires_at = datetime.now() - timedelta(seconds=1)
    with session_scope() as session:
        assert triggers._try_acquire_lock(session, "unit-lock", timedelta(seconds=10))
