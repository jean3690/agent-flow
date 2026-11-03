#!/usr/bin/env python3
"""端到端冒烟测试：对运行中的整栈（默认 http://127.0.0.1:8084）验证核心链路。

覆盖：登录 / 服务商列表 / 知识库(导入-索引-检索) / 工作流执行与断点续跑 / 执行记录删除。
只依赖标准库。用法：先 `./start.sh` 或 `docker compose up`，再 `make e2e`。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AGENTFLOW_BASE_URL", "http://127.0.0.1:8084").rstrip("/")
ADMIN = os.environ.get("AGENTFLOW_ADMIN", "admin")
PASSWORD = os.environ.get("AGENTFLOW_PASSWORD", "admin123")

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + ("" if cond else f" - {detail}"))
    if not cond:
        failures.append(name)


def api(method: str, path: str, token: str | None = None, payload=None):
    request = urllib.request.Request(BASE + path, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    data = json.dumps(payload).encode() if payload is not None else None
    try:
        with urllib.request.urlopen(request, data=data, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body or b"{}")
        except Exception:
            return error.code, {"raw": body.decode("utf-8", "ignore")}


def run_sse(token: str, workflow_id: int, payload: dict) -> list[tuple[str, dict]]:
    request = urllib.request.Request(f"{BASE}/api/workflows/{workflow_id}/execute", method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "text/event-stream")
    request.add_header("Authorization", "Bearer " + token)
    events: list[tuple[str, dict]] = []
    event = ""
    with urllib.request.urlopen(request, data=json.dumps(payload).encode(), timeout=120) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:") and event:
                try:
                    events.append((event, json.loads(line[5:].strip())))
                except json.JSONDecodeError:
                    pass
    return events


def main() -> int:
    status, body = api("POST", "/api/auth/login", payload={"username": ADMIN, "password": PASSWORD})
    token = body.get("data", {}).get("token", "")
    check("登录", status == 200 and token, f"status={status}")
    if not token:
        return 1

    status, body = api("GET", "/api/llm-providers", token)
    providers = body.get("data") or []
    mock = next((item for item in providers if item["provider"] == "mock"), None)
    check("服务商列表含 mock 且可用", status == 200 and mock is not None and mock["configured"])

    # 知识库：导入 → 索引 → 检索
    status, body = api("POST", "/api/knowledge-bases", token, payload={
        "name": "e2e知识库", "description": "smoke", "embeddingProvider": "mock",
        "chunkSize": 200, "chunkOverlap": 40,
    })
    kb_id = body.get("data", {}).get("id")
    check("创建知识库", status == 200 and kb_id, f"status={status}")

    status, body = api("POST", f"/api/knowledge-bases/{kb_id}/documents/text", token, payload={
        "title": "退款政策",
        "content": "退款会在审核通过后 3 个工作日内原路退回。\n超过 30 天的订单不支持无理由退款。",
    })
    doc_id = body.get("data", {}).get("id")
    check("导入文档", status == 200 and doc_id, f"status={status}")

    status, body = api("POST", f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/index", token)
    indexed = body.get("data", {})
    check("建立索引", status == 200 and indexed.get("status") == "INDEXED", json.dumps(indexed, ensure_ascii=False)[:120])

    status, body = api("POST", f"/api/knowledge-bases/{kb_id}/search", token, payload={
        "query": "退款多久到账", "topK": 2,
    })
    hits = body.get("data") or []
    check("知识检索命中", status == 200 and hits and "退款" in hits[0]["content"],
          json.dumps(hits[:1], ensure_ascii=False)[:160])

    # 工作流：input → template → http(必失败) → output；验证失败与断点续跑
    flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["topic"]}},
            {"id": "tpl", "type": "template", "name": "模板", "position": {"x": 1, "y": 0},
             "config": {"template": "关于{{input.topic}}的一句话摘要"}},
            {"id": "http", "type": "http", "name": "必失败", "position": {"x": 2, "y": 0},
             "config": {"method": "GET", "url": "http://127.0.0.1:9/", "timeoutMs": 3000}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 3, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "tpl"},
            {"id": "e2", "source": "tpl", "target": "http"},
            {"id": "e3", "source": "http", "target": "out"},
        ],
    }
    status, body = api("POST", "/api/workflows", token, payload={
        "name": "e2e冒烟工作流", "description": "smoke", "engineType": "langgraph", "status": 1, "flow": flow,
    })
    workflow_id = body.get("data", {}).get("id")
    check("创建工作流", status == 200 and workflow_id, f"status={status}")

    events = run_sse(token, workflow_id, {"input": {"topic": "大海"}})
    failed = next((data for name, data in events if name == "run_failed"), None)
    check("首跑在 http 节点失败", failed is not None and failed.get("status") == "failed")
    run1 = failed.get("runId", "") if failed else ""

    tpl_1 = next((data.get("output") for name, data in events
                  if name == "node_finished" and data.get("nodeId") == "tpl"), None)

    events = run_sse(token, workflow_id, {"input": {"topic": "大海"}, "resumeRunId": run1})
    reused = any(name == "node_log" and "复用上次执行结果" in data.get("message", "")
                 for name, data in events)
    tpl_2 = next((data.get("output") for name, data in events
                  if name == "node_finished" and data.get("nodeId") == "tpl"), None)
    check("断点续跑复用模板输出", reused and tpl_1 == tpl_2 and tpl_2 is not None,
          f"reused={reused} tpl1={tpl_1} tpl2={tpl_2}")

    # 清理：执行记录 → 工作流 → 知识库
    status, body = api("GET", f"/api/executions?page=1&size=50&workflowId={workflow_id}", token)
    records = body.get("data", {}).get("records") or []
    deleted_all = True
    for item in records:
        status, _ = api("DELETE", f"/api/executions/{item['runId']}", token)
        deleted_all = deleted_all and status == 200
    check("删除执行记录", deleted_all and records, f"count={len(records)}")

    status, body = api("GET", f"/api/executions/{run1}", token)
    check("执行记录已不可见", status == 404, f"status={status}")

    status, _ = api("DELETE", f"/api/workflows/{workflow_id}", token)
    check("删除工作流", status == 200)
    status, _ = api("DELETE", f"/api/knowledge-bases/{kb_id}", token)
    check("删除知识库", status == 200)

    print()
    if failures:
        print(f"共 {len(failures)} 项失败: {', '.join(failures)}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
