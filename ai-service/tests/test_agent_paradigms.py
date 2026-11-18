import asyncio
import json

import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.graph.runner import WorkflowRunner
from app.nodes import agent_paradigms
from app.nodes.agent_paradigms import (
    EvaluatorNodeExecutor,
    LlmRouterNodeExecutor,
    MultiAgentNodeExecutor,
    OrchestratorNodeExecutor,
    PlanExecuteNodeExecutor,
    ReflectionNodeExecutor,
    SelfConsistencyNodeExecutor,
)
from app.schemas.execution import ExecutionRequest
from app.schemas.flow import Flow, FlowNode


def _context(mock: bool = True) -> NodeContext:
    return NodeContext(
        run_id="run-paradigm",
        settings=Settings(mock_mode="always" if mock else "never"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        workflow_id="42",
        user_id=7,
    )


def _run(executor, node, state=None, ctx=None):
    return asyncio.run(executor.execute(node, state or {"input": {}}, ctx or _context()))


def _fake_chat(monkeypatch, replies):
    queue = list(replies)
    calls = []

    async def fake(ctx, provider, model, system, user, **kwargs):
        calls.append({"system": system, "user": user})
        if not queue:
            raise AssertionError("unexpected extra model call")
        return queue.pop(0), {"input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(agent_paradigms, "_chat", fake)
    return calls


def test_plan_execute_mock_outputs_steps():
    node = FlowNode(id="plan", type="plan_execute", config={"provider": "mock", "goal": "写一份周报"})
    result = _run(PlanExecuteNodeExecutor(), node)
    assert result["stepCount"] == 3
    assert len(result["results"]) == 3
    assert result["mock"] is True
    assert "周报" in result["text"]


def test_plan_execute_parses_json_plan(monkeypatch):
    calls = _fake_chat(monkeypatch, ['["收集数据","撰写结论"]', "结果一", "结果二"])
    node = FlowNode(id="plan", type="plan_execute", config={
        "provider": "openai", "model": "gpt-4o-mini", "goal": "写周报",
        "maxSteps": 2, "synthesize": False,
    })
    result = _run(PlanExecuteNodeExecutor(), node, ctx=_context(mock=False))
    assert result["plan"] == ["收集数据", "撰写结论"]
    assert result["stepCount"] == 2
    assert "结果一" in result["text"]
    assert len(calls) == 3


def test_plan_execute_parses_numbered_fallback(monkeypatch):
    _fake_chat(monkeypatch, ["1. 第一步\n2. 第二步", "A", "B"])
    node = FlowNode(id="plan", type="plan_execute", config={
        "provider": "openai", "goal": "目标", "maxSteps": 2, "synthesize": False,
    })
    result = _run(PlanExecuteNodeExecutor(), node, ctx=_context(mock=False))
    assert result["plan"] == ["第一步", "第二步"]


def test_reflection_uses_critique_score(monkeypatch):
    _fake_chat(monkeypatch, ["初稿", '{"score": 92, "issues": [], "suggestions": "无需修改"}'])
    node = FlowNode(id="ref", type="reflection", config={
        "provider": "openai", "prompt": "写摘要", "maxRounds": 2, "threshold": 85,
    })
    result = _run(ReflectionNodeExecutor(), node, ctx=_context(mock=False))
    assert result["score"] == 92
    assert result["roundsUsed"] == 1
    assert result["text"] == "初稿"


def test_reflection_rewrites_until_threshold(monkeypatch):
    _fake_chat(monkeypatch, [
        "初稿",
        '{"score": 40, "issues": ["太短"], "suggestions": "补充细节"}',
        "二稿",
        '{"score": 90, "issues": []}',
    ])
    node = FlowNode(id="ref", type="reflection", config={
        "provider": "openai", "prompt": "写摘要", "maxRounds": 2, "threshold": 85,
    })
    result = _run(ReflectionNodeExecutor(), node, ctx=_context(mock=False))
    assert result["text"] == "二稿"
    assert result["roundsUsed"] == 2
    assert result["score"] == 90


def test_reflection_mock_runs_rounds():
    node = FlowNode(id="ref", type="reflection", config={
        "provider": "mock", "prompt": "写摘要", "maxRounds": 2, "threshold": 95,
    })
    result = _run(ReflectionNodeExecutor(), node)
    assert result["roundsUsed"] == 3
    assert result["score"] == 100
    assert result["mock"] is True


def test_multi_agent_mock_builds_transcript():
    agents = '[{"name":"产品","role":"关注价值"},{"name":"工程","role":"关注成本"}]'
    node = FlowNode(id="team", type="multi_agent", config={
        "provider": "mock", "topic": "是否上线", "agents": agents, "rounds": 2,
    })
    result = _run(MultiAgentNodeExecutor(), node)
    assert len(result["transcript"]) == 4
    assert result["agentCount"] == 2
    assert result["rounds"] == 2


def test_multi_agent_requires_two_roles():
    node = FlowNode(id="team", type="multi_agent", config={
        "provider": "mock", "topic": "x", "agents": '[{"name":"单人","role":"全干"}]',
    })
    with pytest.raises(NodeExecutionError):
        _run(MultiAgentNodeExecutor(), node)


def test_multi_agent_real_flow(monkeypatch):
    agents = '[{"name":"产品","role":"价值"},{"name":"工程","role":"成本"}]'
    calls = _fake_chat(monkeypatch, ["价值观点", "成本观点", "综合结论"])
    node = FlowNode(id="team", type="multi_agent", config={
        "provider": "openai", "topic": "是否上线", "agents": agents, "rounds": 1,
    })
    result = _run(MultiAgentNodeExecutor(), node, ctx=_context(mock=False))
    assert len(calls) == 3
    assert [item["agent"] for item in result["transcript"]] == ["产品", "工程"]
    assert result["text"] == "综合结论"


def test_evaluator_threshold_and_feedback(monkeypatch):
    _fake_chat(monkeypatch, ['{"score": 40, "issues": ["缺少来源"], "feedback": "补充引用"}'])
    node = FlowNode(id="eval", type="evaluator", config={
        "provider": "openai", "content": "候选内容", "threshold": 70,
    })
    result = _run(EvaluatorNodeExecutor(), node, ctx=_context(mock=False))
    assert result["passed"] is False
    assert result["score"] == 40
    assert result["issues"] == ["缺少来源"]
    assert result["feedback"] == "补充引用"


def test_evaluator_fail_on_low_raises(monkeypatch):
    _fake_chat(monkeypatch, ['{"score": 20, "issues": [], "feedback": "不合格"}'])
    node = FlowNode(id="eval", type="evaluator", config={
        "provider": "openai", "content": "内容", "threshold": 60, "failOnLow": True,
    })
    with pytest.raises(NodeExecutionError) as error:
        _run(EvaluatorNodeExecutor(), node, ctx=_context(mock=False))
    assert "评审未通过" in error.value.message


def test_evaluator_mock_passes():
    node = FlowNode(id="eval", type="evaluator", config={"provider": "mock", "content": "内容"})
    result = _run(EvaluatorNodeExecutor(), node)
    assert result["passed"] is True
    assert result["mock"] is True


def test_self_consistency_aggregates_and_reports_agreement(monkeypatch):
    _fake_chat(monkeypatch, ["答案 A", "答案 A", "最终答案 A"])
    node = FlowNode(id="vote", type="self_consistency", config={
        "provider": "openai", "prompt": "回答问题", "samples": 2,
    })
    result = _run(SelfConsistencyNodeExecutor(), node, ctx=_context(mock=False))
    assert result["samples"] == 2
    assert result["agreement"] == 1.0
    assert result["candidates"] == ["答案 A", "答案 A"]
    assert result["text"] == "最终答案 A"


def test_self_consistency_mock_samples():
    node = FlowNode(id="vote", type="self_consistency", config={
        "provider": "mock", "prompt": "问题", "samples": 3,
    })
    result = _run(SelfConsistencyNodeExecutor(), node)
    assert len(result["candidates"]) == 3
    assert result["samples"] == 3
    assert result["mock"] is True


def _router_context(mock: bool = True) -> NodeContext:
    ctx = _context(mock)
    ctx.flow = Flow(nodes=[
        FlowNode(id="tech", type="template", config={}),
        FlowNode(id="life", type="template", config={}),
    ], edges=[])
    return ctx


def _router_routes() -> str:
    return json.dumps([
        {"name": "技术", "description": "代码、报错、架构", "target": "tech"},
        {"name": "生活", "description": "日常、健康、饮食", "target": "life"},
    ], ensure_ascii=False)


def test_router_mock_matches_keyword_and_target():
    node = FlowNode(id="router", type="llm_router", config={
        "provider": "mock", "input": "生活问题：晚饭吃什么", "routes": _router_routes(),
    })
    result = _run(LlmRouterNodeExecutor(), node, ctx=_router_context())
    assert result["route"] == "生活"
    assert result["target"] == "life"
    assert result["mock"] is True


def test_router_uses_model_json_and_fallback(monkeypatch):
    _fake_chat(monkeypatch, ['{"route":"技术","reason":"包含报错信息","confidence":0.92}'])
    node = FlowNode(id="router", type="llm_router", config={
        "provider": "openai", "input": "接口 500 报错", "routes": _router_routes(),
        "fallbackTarget": "life",
    })
    result = _run(LlmRouterNodeExecutor(), node, ctx=_router_context(mock=False))
    assert result["route"] == "技术"
    assert result["target"] == "tech"
    assert result["confidence"] == 0.92
    assert result["reason"] == "包含报错信息"


def test_router_unknown_route_uses_fallback(monkeypatch):
    _fake_chat(monkeypatch, ['{"route":"财务","reason":"不确定"}'])
    node = FlowNode(id="router", type="llm_router", config={
        "provider": "openai", "input": "季度报表", "routes": _router_routes(),
        "fallbackTarget": "life",
    })
    result = _run(LlmRouterNodeExecutor(), node, ctx=_router_context(mock=False))
    assert result["route"] == ""
    assert result["target"] == "life"


def test_router_rejects_unknown_target():
    node = FlowNode(id="router", type="llm_router", config={
        "provider": "mock", "input": "x",
        "routes": '[{"name":"A","description":"","target":"ghost"}]',
    })
    with pytest.raises(NodeExecutionError):
        _run(LlmRouterNodeExecutor(), node, ctx=_router_context())


def test_router_rejects_empty_routes():
    node = FlowNode(id="router", type="llm_router", config={
        "provider": "mock", "input": "x", "routes": "[]",
    })
    with pytest.raises(NodeExecutionError):
        _run(LlmRouterNodeExecutor(), node, ctx=_router_context())


async def _run_router_flow(inputs):
    flow = Flow.model_validate({
        "nodes": [
            {"id": "start", "type": "input", "config": {"variables": ["topic"]}},
            {"id": "router", "type": "llm_router", "config": {
                "provider": "mock", "input": "{{input.topic}}",
                "routes": _router_routes(), "fallbackTarget": "life",
            }},
            {"id": "tech", "type": "template", "config": {"template": "TECH:{{input.topic}}"}},
            {"id": "life", "type": "template", "config": {"template": "LIFE:{{input.topic}}"}},
            {"id": "end", "type": "output", "config": {"template": "{{tech.text}}{{life.text}}"}},
        ],
        "edges": [
            {"source": "start", "target": "router"},
            {"source": "tech", "target": "end"},
            {"source": "life", "target": "end"},
        ],
    })
    request = ExecutionRequest.model_validate({
        "runId": "router-run", "workflowId": "1",
        "flow": flow.model_dump(by_alias=True), "input": inputs,
    })
    bus = EventBus()
    await WorkflowRunner(request, bus, Settings(mock_mode="always")).run()
    chunks = []
    async for chunk in bus.drain():
        chunks.append(chunk)
    return "".join(chunks)


def test_router_flow_executes_only_selected_branch():
    log = asyncio.run(_run_router_flow({"topic": "生活"}))
    assert "LIFE:生活" in log
    assert "TECH" not in log



def _worker_flow(prefix: str) -> Flow:
    return Flow.model_validate({
        "nodes": [
            {"id": "in", "type": "input"},
            {"id": "tpl", "type": "template", "config": {"template": f"{prefix}:{{{{input.task}}}}"}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"source": "in", "target": "tpl"},
            {"source": "tpl", "target": "out"},
        ],
    })


def _orchestrator_context(mock: bool = True) -> NodeContext:
    ctx = _context(mock)
    ctx.subflows = {"1": _worker_flow("A"), "2": _worker_flow("B")}
    return ctx


def _orchestrator_workers() -> str:
    return json.dumps([
        {"name": "调研员", "description": "收集资料", "workflowId": "1"},
        {"name": "撰写员", "description": "整理成稿", "workflowId": "2"},
    ], ensure_ascii=False)


def test_orchestrator_mock_runs_selected_workers():
    node = FlowNode(id="orch", type="orchestrator", config={
        "provider": "mock", "task": "写一份周报", "workers": _orchestrator_workers(),
        "maxWorkers": 2, "concurrency": 2,
    })
    result = _run(OrchestratorNodeExecutor(), node, ctx=_orchestrator_context())
    assert result["selectedWorkers"] == ["调研员", "撰写员"]
    assert result["workerCount"] == 2
    assert len(result["results"]) == 2
    assert any("A:写一份周报" in (item.get("text") or "") for item in result["results"])
    assert any("B:写一份周报" in (item.get("text") or "") for item in result["results"])
    assert result["mock"] is True


def test_orchestrator_uses_planner_and_aggregator(monkeypatch):
    calls = _fake_chat(monkeypatch, ['{"workers":["撰写员"],"reason":"更合适"}', "汇总交付"])
    node = FlowNode(id="orch", type="orchestrator", config={
        "provider": "openai", "task": "写周报", "workers": _orchestrator_workers(),
        "maxWorkers": 2, "aggregate": True,
    })
    result = _run(OrchestratorNodeExecutor(), node, ctx=_orchestrator_context(mock=False))
    assert len(calls) == 2
    assert result["selectedWorkers"] == ["撰写员"]
    assert result["reason"] == "更合适"
    assert result["results"][0]["text"] == "B:写周报"
    assert result["text"] == "汇总交付"


def test_orchestrator_can_skip_aggregation(monkeypatch):
    _fake_chat(monkeypatch, ["[]"])
    node = FlowNode(id="orch", type="orchestrator", config={
        "provider": "openai", "task": "写周报", "workers": _orchestrator_workers(),
        "maxWorkers": 1, "aggregate": False,
    })
    result = _run(OrchestratorNodeExecutor(), node, ctx=_orchestrator_context(mock=False))
    assert result["selectedWorkers"] == ["调研员"]
    assert "A:写周报" in result["text"]


def test_orchestrator_requires_inlined_worker():
    node = FlowNode(id="orch", type="orchestrator", config={
        "provider": "mock", "task": "x",
        "workers": '[{"name":"外部","description":"","workflowId":"99"}]',
    })
    with pytest.raises(NodeExecutionError):
        _run(OrchestratorNodeExecutor(), node, ctx=_orchestrator_context())


def test_orchestrator_rejects_empty_workers():
    node = FlowNode(id="orch", type="orchestrator", config={
        "provider": "mock", "task": "x", "workers": "[]",
    })
    with pytest.raises(NodeExecutionError):
        _run(OrchestratorNodeExecutor(), node, ctx=_orchestrator_context())

