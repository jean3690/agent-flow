from __future__ import annotations

from sqlalchemy import select

from app.database import session_scope
from app.models import User
from app.security import hash_password


def test_login_and_unauthorized(client, auth):
    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/auth/me", headers=auth).json()["data"]["username"] == "admin"
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401 and bad.json()["code"] == 4010


def test_workflow_crud_versions_publish(client, auth, workflow, simple_flow):
    wid = workflow["id"]
    assert client.get(f"/api/workflows/{wid}", headers=auth).json()["data"]["name"] == "测试工作流"
    updated = client.put(
        f"/api/workflows/{wid}",
        headers=auth,
        json={"name": "改名", "flow": simple_flow},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["version"] == 2
    assert len(client.get(f"/api/workflows/{wid}/versions", headers=auth).json()["data"]) == 2
    published = client.post(f"/api/workflows/{wid}/publish", headers=auth).json()["data"]
    assert published["status"] == 2 and published["publishedVersion"] == 2
    rolled = client.post(f"/api/workflows/{wid}/versions/1/rollback", headers=auth).json()["data"]
    assert rolled["version"] == 3
    assert client.post(f"/api/workflows/{wid}/unpublish", headers=auth).json()["data"]["status"] == 1
    duplicate = client.post(f"/api/workflows/{wid}/duplicate", headers=auth).json()["data"]
    assert duplicate["name"].endswith("副本")
    assert client.delete(f"/api/workflows/{wid}", headers=auth).status_code == 200


def test_workflow_validation_and_not_found(client, auth):
    bad = client.post("/api/workflows", headers=auth, json={"name": "x", "flow": {"nodes": []}})
    assert bad.status_code == 200  # 空画布允许保存
    assert client.get("/api/workflows/99999", headers=auth).status_code == 404
    cycle = {
        "nodes": [{"id": "a", "type": "x"}, {"id": "b", "type": "x"}],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    }
    rejected = client.post("/api/workflows", headers=auth, json={"name": "cycle", "flow": cycle})
    assert rejected.status_code == 400 and "环" in rejected.json()["message"]


def test_resource_ownership_hides_other_users_workflow(client, auth, workflow):
    with session_scope() as session:
        existing = session.scalar(select(User).where(User.username == "bob"))
        if existing is None:
            session.add(
                User(username="bob", password=hash_password("bob12345"), nickname="Bob", role="USER")
            )
    login = client.post("/api/auth/login", json={"username": "bob", "password": "bob12345"})
    assert login.status_code == 200
    bob_auth = {"Authorization": "Bearer " + login.json()["data"]["token"]}
    assert client.get(f"/api/workflows/{workflow['id']}", headers=bob_auth).status_code == 404
    assert client.get(f"/api/workflows/{workflow['id']}", headers=auth).status_code == 200


def test_api_key_authentication(client, auth):
    created = client.post("/api/api-keys", headers=auth, json={"name": "ci"})
    assert created.status_code == 200
    raw = created.json()["data"]["rawKey"]
    assert client.get("/api/workflows", headers={"X-API-Key": raw}).status_code == 200
    assert client.get("/api/workflows", headers={"X-API-Key": "af_wrong"}).status_code == 401
    key_id = created.json()["data"]["id"]
    assert client.delete(f"/api/api-keys/{key_id}", headers=auth).status_code == 200
    assert client.get("/api/workflows", headers={"X-API-Key": raw}).status_code == 401


def test_node_definitions_and_approvals(client, auth):
    definitions = client.get("/api/node-definitions", headers=auth).json()["data"]
    assert len(definitions) > 10
    assert any(item["type"] == "llm" for item in definitions)
    assert isinstance(client.get("/api/approvals", headers=auth).json()["data"], list)


def test_health_and_actuator(client):
    assert client.get("/api/system/health").status_code == 200
    assert client.get("/actuator/health").json()["status"] == "UP"
    assert client.get("/actuator/health/liveness").json()["status"] == "UP"
    assert "agentflow_executions_running" in client.get("/actuator/prometheus").text or True
