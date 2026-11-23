#!/usr/bin/env python3
"""端到端冒烟测试：对运行中的整栈（默认 http://127.0.0.1:8084）验证核心链路。

覆盖：登录 / 服务商列表 / 知识库(导入-索引-检索) / 工作流执行与断点续跑 / 执行记录删除。
只依赖标准库。用法：先 `./start.sh` 或 `docker compose up`，再 `make e2e`。
"""
from __future__ import annotations

import json
import os
import sys
import time
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


def create_workflow(token: str, flow: dict, name: str = "e2e节点") -> int | None:
    status, body = api("POST", "/api/workflows", token, payload={
        "name": name, "description": "smoke", "engineType": "langgraph",
        "status": 1, "flow": flow,
    })
    return body.get("data", {}).get("id") if status == 200 else None


def run_status(events: list[tuple[str, dict]]) -> str:
    for name, data in events:
        if name in ("run_finished", "run_failed"):
            return data.get("status", "")
    return ""


def node_output(events: list[tuple[str, dict]], node_id: str) -> dict | None:
    for name, data in events:
        if name == "node_finished" and data.get("nodeId") == node_id:
            return data.get("output")
    return None


def test_node(token: str, node_id: str, node_type: str, config: dict,
              payload: dict, name: str) -> bool:
    """创建 input -> node -> output 工作流并跑通，返回是否成功（自动清理）。"""
    variables = list(payload.get("input", {}).keys())
    flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": variables}},
            {"id": node_id, "type": node_type, "name": name, "position": {"x": 1, "y": 0},
             "config": config},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": node_id},
            {"id": "e2", "source": node_id, "target": "out"},
        ],
    }
    wid = create_workflow(token, flow, name=name)
    if not wid:
        return False
    try:
        events = run_sse(token, wid, payload)
        return run_status(events) == "success" and node_output(events, node_id) is not None
    finally:
        api("DELETE", f"/api/workflows/{wid}", token)


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

    # 知识库节点：通过工作流执行触发 Python→平台服务内部检索（RAG 全链路）
    knowledge_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["q"]}},
            {"id": "kb", "type": "knowledge", "name": "知识检索", "position": {"x": 1, "y": 0},
             "config": {"knowledgeBaseId": kb_id, "query": "{{input.q}}", "topK": 2}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "kb"},
            {"id": "e2", "source": "kb", "target": "out"},
        ],
    }
    wid = create_workflow(token, knowledge_flow, name="知识库节点")
    if wid:
        events = run_sse(token, wid, {"input": {"q": "退款多久到账"}})
        kb_out = node_output(events, "kb")
        check("知识库节点(RAG)检索命中", run_status(events) == "success" and kb_out
              and "退款" in (kb_out.get("text") or ""), str(kb_out)[:160])
        api("DELETE", f"/api/workflows/{wid}", token)

    # 知识写入节点：运行期写库 → 立即索引 → 管理员检索命中
    upsert_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["text"]}},
            {"id": "kbw", "type": "knowledge_upsert", "name": "知识写入", "position": {"x": 1, "y": 0},
             "config": {"knowledgeBaseId": kb_id, "title": "e2e沉淀",
                        "content": "{{input.text}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "kbw"},
            {"id": "e2", "source": "kbw", "target": "out"},
        ],
    }
    wid = create_workflow(token, upsert_flow, name="知识写入节点")
    if wid:
        events = run_sse(token, wid, {"input": {"text": "AgentFlow 支持在运行期沉淀知识。"}})
        kbw_out = node_output(events, "kbw") or {}
        check("知识写入节点建索引", run_status(events) == "success"
              and kbw_out.get("status") == "INDEXED" and (kbw_out.get("chunkCount") or 0) > 0,
              str(kbw_out)[:160])
        status, body = api("POST", f"/api/knowledge-bases/{kb_id}/search", token,
                           payload={"query": "运行期沉淀知识", "topK": 2})
        hits = body.get("data") or []
        check("知识写入后可检索", status == 200 and hits and "沉淀" in hits[0].get("content", ""),
              json.dumps(hits[:1], ensure_ascii=False)[:160])
        if kbw_out.get("documentId"):
            api("DELETE", f"/api/knowledge-bases/{kb_id}/documents/{kbw_out['documentId']}", token)
        api("DELETE", f"/api/workflows/{wid}", token)

    # RAG 增强节点：多路召回 / HyDE / 重排 → 引用问答
    check("多路召回节点(mock)执行", test_node(
        token, "mq", "multi_query_retrieve",
        {"provider": "mock", "knowledgeBaseId": kb_id, "query": "{{input.q}}",
         "numQueries": 2, "topK": 2, "finalTopK": 3},
        {"input": {"q": "退款多久到账"}}, "多路召回"))
    check("HyDE 召回节点(mock)执行", test_node(
        token, "hyde", "hyde_retrieve",
        {"provider": "mock", "knowledgeBaseId": kb_id, "query": "{{input.q}}",
         "topK": 2, "finalTopK": 3},
        {"input": {"q": "退款多久到账"}}, "HyDE召回"))

    rag_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["q"]}},
            {"id": "kb", "type": "knowledge", "name": "知识检索", "position": {"x": 1, "y": 0},
             "config": {"knowledgeBaseId": kb_id, "query": "{{input.q}}", "topK": 4}},
            {"id": "rk", "type": "rerank", "name": "重排", "position": {"x": 2, "y": 0},
             "config": {"provider": "mock", "query": "{{input.q}}", "topK": 2}},
            {"id": "ans", "type": "rag_answer", "name": "引用问答", "position": {"x": 3, "y": 0},
             "config": {"provider": "mock", "query": "{{input.q}}", "requireCitations": True}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 4, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "kb"},
            {"id": "e2", "source": "kb", "target": "rk"},
            {"id": "e3", "source": "rk", "target": "ans"},
            {"id": "e4", "source": "ans", "target": "out"},
        ],
    }
    wid = create_workflow(token, rag_flow, name="RAG增强链路")
    if wid:
        events = run_sse(token, wid, {"input": {"q": "退款多久到账"}})
        ans_out = node_output(events, "ans") or {}
        check("重排 + 引用问答链路", run_status(events) == "success"
              and (ans_out.get("count") or 0) > 0
              and ans_out.get("citations")
              and "退款" in (ans_out.get("text") or ""), str(ans_out)[:200])
        api("DELETE", f"/api/workflows/{wid}", token)

    # 长期记忆：写入 → 同流程召回
    memory_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["fact"]}},
            {"id": "memw", "type": "memory_write", "name": "写入记忆", "position": {"x": 1, "y": 0},
             "config": {"scope": "workflow", "memoryType": "fact", "content": "{{input.fact}}",
                        "tags": ["e2e"], "provider": "mock"}},
            {"id": "memr", "type": "memory_retrieve", "name": "召回记忆", "position": {"x": 2, "y": 0},
             "config": {"scope": "workflow", "query": "{{input.fact}}", "topK": 3,
                        "tags": ["e2e"], "provider": "mock"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 3, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "memw"},
            {"id": "e2", "source": "memw", "target": "memr"},
            {"id": "e3", "source": "memr", "target": "out"},
        ],
    }
    wid = create_workflow(token, memory_flow, name="长期记忆节点")
    if wid:
        events = run_sse(token, wid, {"input": {"fact": "用户的周报偏好表格排版"}})
        memr_out = node_output(events, "memr") or {}
        check("记忆写入与召回", run_status(events) == "success"
              and (memr_out.get("count") or 0) >= 1 and "表格" in (memr_out.get("context") or ""),
              str(memr_out)[:160])
        api("DELETE", f"/api/workflows/{wid}", token)
        status, body = api("GET", "/api/memories?scope=workflow", token)
        for item in body.get("data") or []:
            if "周报偏好表格" in (item.get("content") or ""):
                api("DELETE", f"/api/memories/{item['id']}", token)

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

    # 节点类型：input -> node(mock) -> output 真实跑通（覆盖 README 宣称能力）
    check("LLM 节点(mock)执行", test_node(
        token, "llm", "llm",
        {"provider": "mock", "model": "agentflow-mock", "prompt": "用一句话介绍{{input.topic}}"},
        {"input": {"topic": "LangGraph"}}, "LLM"))
    check("ReAct 智能体节点(mock)执行", test_node(
        token, "agent", "react_agent",
        {"provider": "mock", "model": "agentflow-mock", "prompt": "回答{{input.q}}", "maxSteps": 3},
        {"input": {"q": "1+1"}}, "ReAct智能体"))
    check("图像生成节点(mock)执行", test_node(
        token, "img", "image_generate",
        {"provider": "mock", "model": "agentflow-mock", "prompt": "一只猫", "size": "512x512"},
        {"input": {}}, "图像生成"))
    check("视觉理解节点(mock)执行", test_node(
        token, "vis", "vision_analyze",
        {"provider": "mock", "model": "agentflow-mock", "imageUrl": "http://example.com/x.png", "prompt": "描述图片"},
        {"input": {}}, "视觉理解"))
    check("视频生成节点(mock)执行", test_node(
        token, "vid", "video_generate",
        {"provider": "mock", "model": "agentflow-mock", "prompt": "日落"},
        {"input": {}}, "视频生成"))
    check("语音合成节点(mock)执行", test_node(
        token, "tts", "tts",
        {"provider": "mock", "voice": "default", "text": "你好", "format": "wav"},
        {"input": {}}, "语音合成"))
    check("计划执行节点(mock)执行", test_node(
        token, "plan", "plan_execute",
        {"provider": "mock", "goal": "{{input.topic}}", "maxSteps": 3},
        {"input": {"topic": "上线方案"}}, "计划执行"))
    check("反思迭代节点(mock)执行", test_node(
        token, "ref", "reflection",
        {"provider": "mock", "prompt": "{{input.topic}}", "maxRounds": 1, "threshold": 80},
        {"input": {"topic": "写摘要"}}, "反思迭代"))
    check("多智能体节点(mock)执行", test_node(
        token, "team", "multi_agent",
        {"provider": "mock", "topic": "{{input.topic}}", "rounds": 1,
         "agents": '[{"name":"产品","role":"价值"},{"name":"工程","role":"成本"}]'},
        {"input": {"topic": "是否上线"}}, "多智能体"))
    check("结果评审节点(mock)执行", test_node(
        token, "eval", "evaluator",
        {"provider": "mock", "content": "候选内容", "threshold": 70},
        {"input": {}}, "结果评审"))
    check("自洽投票节点(mock)执行", test_node(
        token, "vote", "self_consistency",
        {"provider": "mock", "prompt": "{{input.q}}", "samples": 2},
        {"input": {"q": "回答问题"}}, "自洽投票"))
    check("人工审批节点(mock 自动通过)执行", test_node(
        token, "approval", "human_approval",
        # autoApprove 让冒烟不依赖 AI_MOCK_MODE=always，也不需要人工点通过
        {"title": "发布审批", "content": "{{input.text}}", "waitSeconds": 30, "autoApprove": True},
        {"input": {"text": "准备发布"}}, "人工审批"))

    # 条件分支节点：表达式求值与路由
    cond_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["num"]}},
            {"id": "cond", "type": "condition", "name": "条件", "position": {"x": 1, "y": 0},
             "config": {"expression": "input.num > 1"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "cond"},
            {"id": "e2", "source": "cond", "target": "out"},
        ],
    }
    wid = create_workflow(token, cond_flow, name="条件分支")
    if wid:
        events = run_sse(token, wid, {"input": {"num": 5}})
        cond_out = node_output(events, "cond")
        check("条件分支节点(表达式求值)", run_status(events) == "success" and cond_out
              and cond_out.get("result") is True, str(cond_out))
        api("DELETE", f"/api/workflows/{wid}", token)

    # 意图路由：配置目标节点，按语义只执行命中的分支
    router_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["topic"]}},
            {"id": "router", "type": "llm_router", "name": "意图路由", "position": {"x": 1, "y": 0},
             "config": {
                 "provider": "mock", "input": "{{input.topic}}", "fallbackTarget": "life",
                 "routes": '[{"name":"技术","description":"代码、报错","target":"tech"},{"name":"生活","description":"日常、健康","target":"life"}]',
             }},
            {"id": "tech", "type": "template", "name": "技术分支", "position": {"x": 2, "y": -1},
             "config": {"template": "TECH:{{input.topic}}"}},
            {"id": "life", "type": "template", "name": "生活分支", "position": {"x": 2, "y": 1},
             "config": {"template": "LIFE:{{input.topic}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 3, "y": 0},
             "config": {"template": "{{tech.text}}{{life.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "router"},
            {"id": "e2", "source": "tech", "target": "out"},
            {"id": "e3", "source": "life", "target": "out"},
        ],
    }
    wid = create_workflow(token, router_flow, name="意图路由")
    if wid:
        events = run_sse(token, wid, {"input": {"topic": "生活问题"}})
        route_out = node_output(events, "router") or {}
        check("意图路由只执行命中分支", run_status(events) == "success"
              and route_out.get("route") == "生活"
              and node_output(events, "life") is not None
              and node_output(events, "tech") is None, str(route_out)[:160])
        api("DELETE", f"/api/workflows/{wid}", token)

    # 协调执行：调用两个子工作流并汇总结果
    def worker_flow(prefix: str) -> dict:
        return {
            "nodes": [
                {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
                 "config": {"variables": ["task"]}},
                {"id": "tpl", "type": "template", "name": "执行", "position": {"x": 1, "y": 0},
                 "config": {"template": f"{prefix}:{{{{input.task}}}}"}},
                {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "in", "target": "tpl"},
                {"id": "e2", "source": "tpl", "target": "out"},
            ],
        }

    worker_a = create_workflow(token, worker_flow("WORKER_A"), name="执行者A")
    worker_b = create_workflow(token, worker_flow("WORKER_B"), name="执行者B")
    if worker_a and worker_b:
        workers = json.dumps([
            {"name": "执行者A", "description": "负责第一部分", "workflowId": str(worker_a)},
            {"name": "执行者B", "description": "负责第二部分", "workflowId": str(worker_b)},
        ], ensure_ascii=False)
        orch_flow = {
            "nodes": [
                {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
                 "config": {"variables": ["task"]}},
                {"id": "orch", "type": "orchestrator", "name": "协调执行", "position": {"x": 1, "y": 0},
                 "config": {"provider": "mock", "task": "{{input.task}}", "workers": workers,
                            "maxWorkers": 2, "concurrency": 2}},
                {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "in", "target": "orch"},
                {"id": "e2", "source": "orch", "target": "out"},
            ],
        }
        wid = create_workflow(token, orch_flow, name="协调执行")
        if wid:
            events = run_sse(token, wid, {"input": {"task": "周报"}})
            orch_out = node_output(events, "orch") or {}
            text = orch_out.get("text") or ""
            check("协调执行调用子工作流并汇总", run_status(events) == "success"
                  and orch_out.get("workerCount") == 2
                  and "WORKER_A:周报" in text and "WORKER_B:周报" in text,
                  str(orch_out)[:200])
            api("DELETE", f"/api/workflows/{wid}", token)
        api("DELETE", f"/api/workflows/{worker_a}", token)
        api("DELETE", f"/api/workflows/{worker_b}", token)

    # 可观测性：token 统计 + Actuator 指标
    llm_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["topic"]}},
            {"id": "llm", "type": "llm", "name": "LLM", "position": {"x": 1, "y": 0},
             "config": {"provider": "mock", "model": "agentflow-mock", "prompt": "介绍 {{input.topic}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "llm"},
            {"id": "e2", "source": "llm", "target": "out"},
        ],
    }
    wid = create_workflow(token, llm_flow, name="token统计")
    if wid:
        status, body = api("POST", f"/api/workflows/{wid}/run", token, payload={"input": {"topic": "AgentFlow"}})
        result = body.get("data") or {}
        check("执行 token 统计", status == 200 and (result.get("totalTokens") or 0) > 0,
              f"tokens={result.get('totalTokens')} cost={result.get('costUsd')}")
        if result.get("runId"):
            api("DELETE", f"/api/executions/{result['runId']}", token)
        api("DELETE", f"/api/workflows/{wid}", token)

    try:
        with urllib.request.urlopen(BASE + "/actuator/health", timeout=10) as response:
            health = json.loads(response.read() or b"{}")
        check("Actuator 健康检查", response.status == 200 and health.get("status") == "UP", str(health)[:80])
        with urllib.request.urlopen(BASE + "/actuator/prometheus", timeout=10) as response:
            metrics = response.read().decode("utf-8", "ignore")
        check("Prometheus 指标暴露", "agentflow_executions_total" in metrics
              and "agentflow_llm_tokens_total" in metrics, f"len={len(metrics)}")
    except Exception as error:  # noqa: BLE001
        check("Actuator 指标", False, str(error))

    # 服务商凭据：保存 → 掩码返回 → 测试连接 → 清除
    status, _ = api("PUT", "/api/llm-providers/mock", token, payload={"apiKey": "sk-test-dummy", "baseUrl": ""})
    check("保存服务商凭据", status == 200, f"status={status}")
    status, body = api("GET", "/api/llm-providers", token)
    mock_cfg = next((i for i in (body.get("data") or []) if i.get("provider") == "mock"), None)
    masked = bool(mock_cfg and mock_cfg.get("configured") and "sk-test" not in (mock_cfg.get("apiKey") or ""))
    check("凭据掩码返回", masked, str(mock_cfg))
    status, body = api("POST", "/api/llm-providers/mock/test", token, payload={})
    check("测试服务商连接(mock)", status == 200 and (body.get("data") or {}).get("ok"),
          json.dumps(body, ensure_ascii=False)[:120])
    # 动态模型列表：mock 走静态兜底，不依赖真实上游，避免冒烟 flaky
    status, body = api("GET", "/api/llm-providers/mock/models", token)
    models = (body.get("data") or {}).get("models") or []
    check("拉取服务商模型列表(mock 静态兜底)", status == 200 and len(models) > 0,
          json.dumps(body, ensure_ascii=False)[:120])
    status, _ = api("DELETE", "/api/llm-providers/mock", token)
    check("清除服务商凭据", status == 200, f"status={status}")

    # 技能系统
    status, body = api("GET", "/api/skills", token)
    skills = body.get("data") or []
    check("技能列表非空", status == 200 and len(skills) > 0, f"count={len(skills)}")

    # 文件 IO：文本写入 → 列表 → 下载 → 节点读写 → 删除
    status, body = api("POST", "/api/files/text", token, payload={
        "name": "e2e/hello.md", "content": "# AgentFlow 文件 IO", "overwrite": True,
    })
    check("写入文本文件", status == 200 and (body.get("data") or {}).get("path") == "e2e/hello.md",
          json.dumps(body, ensure_ascii=False)[:120])

    status, body = api("GET", "/api/files?prefix=e2e/", token)
    items = body.get("data") or []
    check("文件列表包含写入文件", status == 200 and any(i.get("path") == "e2e/hello.md" for i in items),
          f"count={len(items)}")

    try:
        download_request = urllib.request.Request(BASE + "/api/files/e2e/hello.md", headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(download_request, timeout=30) as response:
            downloaded = response.read().decode("utf-8")
        check("下载文件内容一致", downloaded == "# AgentFlow 文件 IO", downloaded[:60])
    except Exception as error:  # noqa: BLE001
        check("下载文件内容一致", False, str(error))

    file_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["suffix"]}},
            {"id": "write", "type": "file_write", "name": "写入文件", "position": {"x": 1, "y": 0},
             "config": {"path": "e2e/node-{{input.suffix}}.txt", "content": "节点写入：{{input.suffix}}"}},
            {"id": "read", "type": "file_read", "name": "读取文件", "position": {"x": 2, "y": 0},
             "config": {"path": "{{write.path}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 3, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "write"},
            {"id": "e2", "source": "write", "target": "read"},
            {"id": "e3", "source": "read", "target": "out"},
        ],
    }
    wid = create_workflow(token, file_flow, name="文件IO")
    if wid:
        events = run_sse(token, wid, {"input": {"suffix": "smoke"}})
        write_out = node_output(events, "write") or {}
        read_out = node_output(events, "read") or {}
        check("文件写入节点执行", run_status(events) == "success"
              and write_out.get("path") == "e2e/node-smoke.txt", str(write_out)[:160])
        check("文件读取节点回读内容", read_out.get("text") == "节点写入：smoke", str(read_out)[:160])
        api("DELETE", f"/api/workflows/{wid}", token)

    for name in ("e2e/hello.md", "e2e/node-smoke.txt"):
        api("DELETE", f"/api/files/{name}", token)
    status, body = api("GET", "/api/files?prefix=e2e/", token)
    check("删除文件后列表为空", status == 200 and not (body.get("data") or []), str(body)[:120])

    # 节点编排：子工作流 → 循环遍历 → 合并 → 延迟 → 容错
    child_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["item"]}},
            {"id": "tpl", "type": "template", "name": "模板", "position": {"x": 1, "y": 0},
             "config": {"template": "子流程处理 {{input.item}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "tpl"},
            {"id": "e2", "source": "tpl", "target": "out"},
        ],
    }
    child_id = create_workflow(token, child_flow, name="编排-子流程")
    check("创建子工作流", child_id is not None, str(child_id))

    check("子工作流节点执行", test_node(
        token, "sub", "subflow",
        {"workflowId": child_id, "input": '{"item": "{{input.topic}}"}'},
        {"input": {"topic": "E2E"}}, "子工作流节点"))

    foreach_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["items"]}},
            {"id": "loop", "type": "foreach", "name": "循环", "position": {"x": 1, "y": 0},
             "config": {"items": "{{input.items}}", "bodyWorkflowId": str(child_id), "concurrency": 2}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "loop"},
            {"id": "e2", "source": "loop", "target": "out"},
        ],
    }
    wid = create_workflow(token, foreach_flow, name="编排-循环")
    if wid:
        events = run_sse(token, wid, {"input": {"items": ["甲", "乙"]}})
        loop_out = node_output(events, "loop") or {}
        outputs = [str(item.get("output")) for item in loop_out.get("results") or []]
        check("循环遍历节点执行", run_status(events) == "success"
              and loop_out.get("count") == 2 and loop_out.get("successCount") == 2
              and any("子流程处理 甲" in item for item in outputs), str(outputs)[:160])
        api("DELETE", f"/api/workflows/{wid}", token)

    merge_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["topic"]}},
            {"id": "a", "type": "template", "name": "分支A", "position": {"x": 1, "y": 0},
             "config": {"template": "A-{{input.topic}}"}},
            {"id": "b", "type": "template", "name": "分支B", "position": {"x": 1, "y": 120},
             "config": {"template": "B-{{input.topic}}"}},
            {"id": "merge", "type": "merge", "name": "合并", "position": {"x": 2, "y": 60},
             "config": {"sources": ["a", "b"], "mode": "object"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 3, "y": 60}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "a"},
            {"id": "e2", "source": "in", "target": "b"},
            {"id": "e3", "source": "a", "target": "merge"},
            {"id": "e4", "source": "b", "target": "merge"},
            {"id": "e5", "source": "merge", "target": "out"},
        ],
    }
    wid = create_workflow(token, merge_flow, name="编排-合并")
    if wid:
        events = run_sse(token, wid, {"input": {"topic": "E2E"}})
        merge_out = node_output(events, "merge") or {}
        check("并行分支合并节点", run_status(events) == "success"
              and merge_out.get("value") == {"a": "A-E2E", "b": "B-E2E"},
              str(merge_out.get("value")))
        api("DELETE", f"/api/workflows/{wid}", token)

    check("延迟节点执行", test_node(
        token, "wait", "delay", {"durationMs": 120}, {"input": {}}, "延迟"))

    fault_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "bad", "type": "http", "name": "失败请求", "position": {"x": 1, "y": 0},
             "config": {"method": "GET", "url": "http://127.0.0.1:9/", "timeoutMs": 800,
                        "retry": 1, "retryDelayMs": 0, "onError": "continue"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0},
             "config": {"template": "{{bad.failed}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "bad"},
            {"id": "e2", "source": "bad", "target": "out"},
        ],
    }
    wid = create_workflow(token, fault_flow, name="编排-容错")
    if wid:
        events = run_sse(token, wid, {"input": {}})
        retried = any(name == "node_log" and data.get("nodeId") == "bad"
                      and "重试" in data.get("message", "") for name, data in events)
        final = next((data for name, data in events if name == "run_finished"), {})
        check("节点重试与失败继续", run_status(events) == "success" and retried
              and final.get("output") is True, f"retried={retried} output={final.get('output')}")
        api("DELETE", f"/api/workflows/{wid}", token)

    timeout_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "slow", "type": "delay", "name": "慢节点", "position": {"x": 1, "y": 0},
             "config": {"durationMs": 400, "timeoutMs": 50, "onError": "continue"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0},
             "config": {"template": "{{slow.failed}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "slow"},
            {"id": "e2", "source": "slow", "target": "out"},
        ],
    }
    wid = create_workflow(token, timeout_flow, name="编排-超时")
    if wid:
        events = run_sse(token, wid, {"input": {}})
        final = next((data for name, data in events if name == "run_finished"), {})
        check("节点超时按失败继续", run_status(events) == "success"
              and final.get("output") is True, str(final.get("output")))
        api("DELETE", f"/api/workflows/{wid}", token)

    api("DELETE", f"/api/workflows/{child_id}", token)

    # 版本与发布：快照 → 发布 → 草稿修改 → 触发器跑发布版 → 回滚
    def _version_flow(text):
        return {
            "nodes": [
                {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
                 "config": {"variables": ["topic"]}},
                {"id": "tpl", "type": "template", "name": "模板", "position": {"x": 1, "y": 0},
                 "config": {"template": text + " {{input.topic}}"}},
                {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
            ],
            "edges": [
                {"id": "e1", "source": "in", "target": "tpl"},
                {"id": "e2", "source": "tpl", "target": "out"},
            ],
        }

    status, body = api("POST", "/api/workflows", token, payload={
        "name": "版本发布测试", "description": "v1", "engineType": "langgraph",
        "status": 1, "flow": _version_flow("版本一"),
    })
    vid = (body.get("data") or {}).get("id")
    check("创建版本化工作流", status == 200 and vid, str(status))

    status, body = api("POST", f"/api/workflows/{vid}/publish", token)
    published = body.get("data") or {}
    check("发布 v1", status == 200 and published.get("publishedVersion") == 1
          and published.get("status") == 2, json.dumps(published, ensure_ascii=False)[:160])

    status, body = api("PUT", f"/api/workflows/{vid}", token, payload={
        "name": "版本发布测试", "description": "v2", "engineType": "langgraph",
        "status": 1, "flow": _version_flow("版本二"),
    })
    updated = body.get("data") or {}
    check("保存新草稿 v2", status == 200 and updated.get("version") == 2
          and updated.get("publishedVersion") == 1, json.dumps(updated, ensure_ascii=False)[:160])

    status, body = api("GET", f"/api/workflows/{vid}/versions", token)
    versions = body.get("data") or []
    check("版本列表含 v1/v2 与发布标记", status == 200
          and {1, 2}.issubset({item.get("version") for item in versions})
          and any(item.get("version") == 1 and item.get("published") for item in versions)
          and any(item.get("version") == 2 and item.get("current") for item in versions),
          json.dumps(versions, ensure_ascii=False)[:180])

    status, body = api("GET", f"/api/workflows/{vid}/versions/1", token)
    check("版本详情返回 flow", status == 200
          and "版本一" in json.dumps((body.get("data") or {}).get("flow"), ensure_ascii=False),
          str(status))

    status, body = api("POST", f"/api/workflows/{vid}/triggers", token, payload={
        "name": "版本 webhook", "type": "WEBHOOK", "input": {}, "enabled": True,
    })
    version_trigger = body.get("data") or {}

    status, body = api("POST", version_trigger.get("webhookPath") or "/missing", payload={"topic": "X"})
    version_run = (body.get("data") or {}).get("runId", "")
    version_detail = {}
    for _ in range(25):
        _, dbg = api("GET", "/api/executions/" + version_run, token)
        version_detail = dbg.get("data") or {}
        if version_detail.get("status") != "RUNNING":
            break
        time.sleep(1)
    check("触发器执行已发布版本", version_detail.get("status") == "SUCCESS"
          and version_detail.get("flowVersion") == 1
          and "版本一 X" in (version_detail.get("output") or ""),
          f"v={version_detail.get('flowVersion')} out={version_detail.get('output')}")

    status, body = api("POST", f"/api/workflows/{vid}/run", token, payload={"input": {"topic": "Y"}})
    manual_out = json.dumps((body.get("data") or {}).get("outputs"), ensure_ascii=False)
    check("手动运行执行当前草稿", status == 200 and "版本二 Y" in manual_out, manual_out[:120])

    status, body = api("POST", f"/api/workflows/{vid}/versions/1/rollback", token)
    rolled = body.get("data") or {}
    check("回滚生成新版本", status == 200 and rolled.get("version") == 3
          and "版本一" in json.dumps(rolled.get("flow"), ensure_ascii=False),
          json.dumps(rolled, ensure_ascii=False)[:160])

    status, body = api("POST", f"/api/workflows/{vid}/run", token, payload={"input": {"topic": "Z"}})
    rollback_out = json.dumps((body.get("data") or {}).get("outputs"), ensure_ascii=False)
    check("回滚后执行回滚内容", status == 200 and "版本一 Z" in rollback_out, rollback_out[:120])

    status, body = api("POST", f"/api/workflows/{vid}/unpublish", token)
    unpublished = body.get("data") or {}
    check("取消发布", status == 200 and unpublished.get("publishedVersion") is None
          and unpublished.get("status") == 1, json.dumps(unpublished, ensure_ascii=False)[:160])

    api("DELETE", f"/api/triggers/{version_trigger.get('id')}", token)
    api("DELETE", f"/api/workflows/{vid}", token)

    # 触发器：Webhook 实际触发 → 手动运行 → CRON 创建/校验 → 删除失效
    trigger_flow = {
        "nodes": [
            {"id": "in", "type": "input", "name": "输入", "position": {"x": 0, "y": 0},
             "config": {"variables": ["topic"]}},
            {"id": "tpl", "type": "template", "name": "模板", "position": {"x": 1, "y": 0},
             "config": {"template": "触发了 {{input.topic}}"}},
            {"id": "out", "type": "output", "name": "输出", "position": {"x": 2, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "in", "target": "tpl"},
            {"id": "e2", "source": "tpl", "target": "out"},
        ],
    }
    wid = create_workflow(token, trigger_flow, name="触发器")
    check("创建触发器工作流", wid is not None, str(wid))

    status, body = api("POST", f"/api/workflows/{wid}/triggers", token, payload={
        "name": "e2e webhook", "type": "WEBHOOK", "input": {"topic": "默认输入"}, "enabled": True,
    })
    trigger = body.get("data") or {}
    webhook_path = trigger.get("webhookPath") or ""
    check("创建 Webhook 触发器", status == 200
          and webhook_path.startswith("/api/triggers/webhook/"), json.dumps(trigger, ensure_ascii=False)[:160])

    status, body = api("POST", webhook_path, payload={"topic": "Webhook 覆盖"})
    run_id = (body.get("data") or {}).get("runId", "")
    check("Webhook 受理执行（免鉴权）", status == 200 and run_id, str(status))

    detail = {}
    for _ in range(30):
        _, dbg = api("GET", "/api/executions/" + run_id, token)
        detail = dbg.get("data") or {}
        if detail.get("status") != "RUNNING":
            break
        time.sleep(1)
    check("Webhook 执行成功", detail.get("status") == "SUCCESS", str(detail.get("errorMessage")))
    check("Webhook 请求体覆盖静态输入", "Webhook 覆盖" in (detail.get("output") or ""),
          str(detail.get("output"))[:120])

    time.sleep(0.5)
    status, body = api("GET", f"/api/workflows/{wid}/triggers", token)
    listed = body.get("data") or []
    check("触发器列表返回最近状态", status == 200 and listed
          and listed[0].get("lastStatus") == "SUCCESS", json.dumps(listed[:1], ensure_ascii=False)[:160])

    status, _ = api("POST", f"/api/triggers/{trigger['id']}/run", token)
    check("手动运行触发器", status == 200, str(status))

    status, body = api("POST", f"/api/workflows/{wid}/triggers", token, payload={
        "name": "e2e cron", "type": "CRON", "cronExpression": "0 9 * * *",
        "timezone": "Asia/Shanghai", "input": {}, "enabled": True,
    })
    cron = body.get("data") or {}
    check("创建 CRON 触发器并计算下次时间", status == 200
          and cron.get("cronExpression") == "0 0 9 * * *" and cron.get("nextRunAt"),
          json.dumps(cron, ensure_ascii=False)[:160])
    api("DELETE", f"/api/triggers/{cron.get('id')}", token)
    api("DELETE", f"/api/triggers/{trigger['id']}", token)

    status, _ = api("POST", webhook_path, payload={})
    check("删除后 Webhook 立即失效", status == 404, str(status))
    api("DELETE", f"/api/workflows/{wid}", token)

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
