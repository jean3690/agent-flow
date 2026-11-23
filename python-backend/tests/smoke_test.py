from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB_PATH = Path(__file__).resolve().parent / "smoke.db"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["PAIAGENT_DATABASE_URL"] = "sqlite:///" + str(DB_PATH)
os.environ["PAIAGENT_AUTO_MIGRATE"] = "true"
os.environ.setdefault("APP_AUTH_DEFAULT_USERNAME", "admin")
os.environ.setdefault("APP_AUTH_DEFAULT_PASSWORD", "admin123")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
    else:
        failures.append(name)
        print(f"FAIL  {name} {detail}")


with client:
    response = client.get("/api/node-types")
    body = response.json()
    types = [item["nodeType"] for item in body.get("data", [])]
    check("node-types no auth", response.status_code == 200 and body["code"] == 200)
    check("node-types hides react_agent", "react_agent" not in types)
    check("node-types has generic llm", "llm" in types)

    response = client.get("/api/workflows")
    check("workflows requires auth", response.status_code == 401 and response.json()["code"] == 401)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    token = response.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}
    check("login", response.json()["code"] == 200 and bool(token))

    flow = {
        "nodes": [
            {"id": "input-1", "type": "input", "data": {"label": "输入", "type": "input"}, "position": {"x": 0, "y": 0}},
            {"id": "output-1", "type": "output", "data": {"label": "输出", "type": "output"}, "position": {"x": 200, "y": 0}},
        ],
        "edges": [{"id": "e1", "source": "input-1", "target": "output-1"}],
    }
    response = client.post(
        "/api/workflows",
        headers=headers,
        json={"name": "smoke", "description": "d", "flowData": json.dumps(flow, ensure_ascii=False)},
    )
    workflow = response.json()["data"]
    check("create workflow", response.json()["code"] == 200 and workflow["id"] > 0)
    workflow_id = workflow["id"]

    response = client.get(f"/api/workflows/{workflow_id}", headers=headers)
    check("get workflow", response.json()["data"]["name"] == "smoke")

    response = client.post(
        f"/api/workflows/{workflow_id}/execute",
        headers=headers,
        json={"inputData": "hello"},
    )
    result = response.json()
    data = result.get("data") or {}
    check("execute workflow", result["code"] == 200 and data.get("status") == "SUCCESS", str(result)[:300])
    check("execute output", json.loads(data.get("outputData") or "{}").get("output") == "hello", str(data.get("outputData")))
    check("execute node results", len(data.get("nodeResults") or []) == 2, str(data.get("nodeResults"))[:200])
    execution_id = data.get("executionId")

    response = client.get(f"/api/workflows/{workflow_id}/executions/latest", headers=headers)
    check("latest execution", response.json()["data"]["executionId"] == execution_id)

    response = client.get(f"/api/workflows/{workflow_id}/executions/{execution_id}/snapshots", headers=headers)
    snapshots = response.json()["data"]
    check("snapshots", len(snapshots) == 2 and snapshots[0]["status"] == "SUCCESS", str(snapshots)[:300])

    response = client.post(
        "/api/llm-config",
        headers=headers,
        json={
            "provider": "deepseek",
            "configName": "smoke",
            "apiUrl": "https://api.deepseek.com",
            "apiKey": "sk-test",
            "model": "deepseek-chat",
            "temperature": 0.5,
        },
    )
    config = response.json()["data"]
    check("save llm config", response.json()["code"] == 200 and config["isDefault"] == 1 and config["temperature"] == 0.5)
    response = client.get("/api/llm-config", headers=headers)
    check("list llm config", len(response.json()["data"]) == 1)
    response = client.get("/api/llm-config/default/deepseek", headers=headers)
    check("default llm config", response.json()["data"]["configName"] == "smoke")

    response = client.get("/api/skills", headers=headers)
    skills = response.json()["data"]
    check("skills loaded", response.json()["code"] == 200 and any(item["name"] == "ai-podcast" for item in skills), str(skills)[:200])

    response = client.post(
        "/api/knowledge-bases",
        headers=headers,
        json={"name": "smoke-kb", "description": "d"},
    )
    base = response.json()["data"]
    check("create knowledge base", response.json()["code"] == 200 and base["id"] > 0)
    base_id = base["id"]

    response = client.post(
        f"/api/knowledge-bases/{base_id}/documents/text",
        headers=headers,
        json={"title": "doc", "content": "PaiAgent 是一个工作流编排平台。输入节点会把用户输入传给下游。"},
    )
    document = response.json()["data"]
    check("import knowledge text", response.json()["code"] == 200 and document["charCount"] > 0)
    document_id = document["id"]

    response = client.post(
        f"/api/knowledge-bases/{base_id}/documents/{document_id}/index",
        headers=headers,
    )
    check("index knowledge document", response.json()["data"]["status"] == "SUCCESS", str(response.json())[:300])

    response = client.post(
        f"/api/knowledge-bases/{base_id}/search",
        headers=headers,
        json={"query": "工作流编排", "topK": 3},
    )
    search = response.json()["data"]
    check("knowledge search", response.json()["code"] == 200 and len(search.get("chunks", [])) > 0, str(search)[:300])

    response = client.get(f"/api/knowledge-bases/{base_id}", headers=headers)
    check("knowledge base detail", len(response.json()["data"]["documents"]) == 1)

    response = client.get("/api/mcp-tools", headers=headers)
    check("mcp tools list", response.json()["code"] == 200)

    response = client.get("/api/auth/current", headers=headers)
    check("current user", response.json()["data"]["username"] == "admin")

    response = client.post("/api/auth/refresh", json={"refreshToken": client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin123"}
    ).json()["data"]["refreshToken"]})
    check("refresh token", response.json()["code"] == 200 and response.json()["data"]["token"])

    response = client.get(
        f"/api/workflows/{workflow_id}/execute/stream",
        params={"inputData": "stream", "token": token},
    )
    text = response.text
    check("sse stream", response.status_code == 200 and "event: WORKFLOW_START" in text and "event: WORKFLOW_COMPLETE" in text, text[:300])

    langflow = {
        "nodes": [
            {"id": "in-l", "type": "input", "data": {"type": "input"}},
            {"id": "out-l", "type": "output", "data": {"type": "output"}},
        ],
        "edges": [{"id": "e-l", "source": "in-l", "target": "out-l"}],
    }
    response = client.post(
        "/api/workflows",
        headers=headers,
        json={"name": "lang", "flowData": json.dumps(langflow), "engineType": "langgraph"},
    )
    lang_id = response.json()["data"]["id"]
    response = client.post(f"/api/workflows/{lang_id}/execute", headers=headers, json={"inputData": "lg"})
    check("langgraph execute", response.json()["data"]["status"] == "SUCCESS", str(response.json())[:300])
    check("langgraph output", json.loads(response.json()["data"]["outputData"] or "{}").get("output") == "lg")

    condflow = {
        "nodes": [
            {"id": "in-c", "type": "input", "data": {"type": "input"}},
            {"id": "cond-c", "type": "condition", "data": {"type": "condition", "conditions": [
                {"id": "condition_0", "field": "input", "operator": "contains", "value": "yes"}
            ]}},
            {"id": "out-yes", "type": "output", "data": {"type": "output", "label": "yes"}},
            {"id": "out-no", "type": "output", "data": {"type": "output", "label": "no"}},
        ],
        "edges": [
            {"id": "e1", "source": "in-c", "target": "cond-c"},
            {"id": "e2", "source": "cond-c", "target": "out-yes", "sourceHandle": "condition_0"},
            {"id": "e3", "source": "cond-c", "target": "out-no", "sourceHandle": "default"},
        ],
    }
    response = client.post(
        "/api/workflows",
        headers=headers,
        json={"name": "cond", "flowData": json.dumps(condflow), "engineType": "dag"},
    )
    cond_id = response.json()["data"]["id"]
    response = client.post(f"/api/workflows/{cond_id}/execute", headers=headers, json={"inputData": "yes please"})
    node_ids = [item["nodeId"] for item in response.json()["data"]["nodeResults"]]
    check("condition branch skip", response.json()["data"]["status"] == "SUCCESS" and "out-yes" in node_ids and "out-no" not in node_ids, str(node_ids))

    failflow = {
        "nodes": [
            {"id": "in-f", "type": "input", "data": {"type": "input"}},
            {"id": "llm-f", "type": "llm", "data": {"type": "llm", "prompt": "hi"}},
            {"id": "out-f", "type": "output", "data": {"type": "output"}},
        ],
        "edges": [
            {"id": "e1", "source": "in-f", "target": "llm-f"},
            {"id": "e2", "source": "llm-f", "target": "out-f"},
        ],
    }
    response = client.post(
        "/api/workflows",
        headers=headers,
        json={"name": "fail", "flowData": json.dumps(failflow), "engineType": "dag"},
    )
    fail_id = response.json()["data"]["id"]
    response = client.post(f"/api/workflows/{fail_id}/execute", headers=headers, json={"inputData": "boom"})
    failed = response.json()["data"]
    check("failed execution", failed["status"] == "FAILED" and "缺少有效的提供商配置" in (failed.get("errorMessage") or ""), str(failed)[:300])

    response = client.get(f"/api/workflows/{fail_id}/executions/{failed['executionId']}/snapshots", headers=headers)
    statuses = [item["status"] for item in response.json()["data"]]
    check("failed snapshot", "FAILED" in statuses, str(statuses))

    response = client.post(
        f"/api/workflows/{fail_id}/executions/{failed['executionId']}/resume",
        headers=headers,
        json={"startNodeId": "out-f", "skipSuccessNodes": True, "useSnapshotVariables": True, "modifiedVariables": {"retry": True}},
    )
    resumed = response.json()["data"]
    check("resume from node", resumed["status"] == "SUCCESS" and resumed["nodeResults"][-1]["nodeId"] == "out-f", str(resumed)[:300])

    response = client.delete(f"/api/workflows/{workflow_id}", headers=headers)
    check("delete workflow", response.json()["code"] == 200)
    response = client.get(f"/api/workflows/{workflow_id}", headers=headers)
    check("deleted workflow hidden", response.json()["code"] == 500)

print()
if failures:
    print("FAILURES:", failures)
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
