import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTFLOW_BASE_URL", "http://127.0.0.1:8084").rstrip("/")
ADMIN = os.environ.get("AGENTFLOW_ADMIN", "admin")
PASSWORD = os.environ.get("AGENTFLOW_PASSWORD", "admin123")


def api(m, p, token=None, api_key=None, payload=None):
    req = urllib.request.Request(BASE + p, method=m)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if api_key:
        req.add_header("X-API-Key", api_key)
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=120) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("  " + detail if detail else ""))
    if not ok:
        sys.exit(1)


FLOW = {
    "nodes": [
        {"id": "in", "type": "input", "name": "input", "position": {"x": 0, "y": 0},
         "config": {"variables": ["topic"]}},
        {"id": "llm", "type": "llm", "name": "llm", "position": {"x": 1, "y": 0},
         "config": {"provider": "mock", "model": "agentflow-mock",
                    "prompt": "introduce {{input.topic}} in one sentence"}},
        {"id": "out", "type": "output", "name": "output", "position": {"x": 2, "y": 0}, "config": {}}
    ],
    "edges": [
        {"id": "e1", "source": "in", "target": "llm"},
        {"id": "e2", "source": "llm", "target": "out"}
    ],
}


def main():
    st, body = api("POST", "/api/auth/login",
                   payload={"username": ADMIN, "password": PASSWORD})
    check("admin login", st == 200 and "token" in body.get("data", {}), str(st))
    token = body["data"]["token"]

    st, body = api("POST", "/api/api-keys", token=token,
                   payload={"name": "svc-verify"})
    check("create api key (JWT)", st == 200 and "rawKey" in body.get("data", {}), str(st))
    raw_key = body["data"]["rawKey"]
    key_id = body["data"]["id"]

    st, body = api("GET", "/api/api-keys", api_key=raw_key)
    check("list api keys via X-API-Key", st == 200 and isinstance(body.get("data"), list), str(st))

    st, body = api("POST", "/api/workflows", api_key=raw_key, payload={
        "name": "svc-verify-wf", "description": "x", "engineType": "langgraph",
        "status": 1, "flow": FLOW})
    check("create workflow via X-API-Key", st == 200 and "id" in body.get("data", {}), str(st))
    wid = body["data"]["id"]

    st, body = api("POST", "/api/workflows/%d/run" % wid, api_key=raw_key,
                   payload={"input": {"topic": "LangGraph"}})
    ok = st == 200 and (body.get("data") or {}).get("status") == "SUCCESS"
    check("sync run via X-API-Key", ok, (body.get("data") or {}).get("status", str(st)))

    st, body = api("GET", "/api/workflows", api_key="af_wrongkey")
    check("wrong api key rejected (401)", st == 401, str(st))

    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + "/swagger-ui.html"), timeout=10) as resp:
            html = resp.read().decode("utf-8", "ignore")
        check("swagger-ui served", resp.status == 200 and "swagger" in html.lower(), str(resp.status))
    except Exception as e:  # noqa: BLE001
        check("swagger-ui served", False, str(e))

    api("DELETE", "/api/workflows/%d" % wid, api_key=raw_key)
    api("DELETE", "/api/api-keys/%d" % key_id, token=token)
    print("ALL SERVICE CALL CHECKS PASSED")


if __name__ == "__main__":
    main()
