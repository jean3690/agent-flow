import asyncio

import pytest

from app.config import get_settings
from app.core.errors import FlowValidationError
from app.core.events import EventBus
from app.graph.compiler import validate_flow
from app.graph.runner import WorkflowRunner
from app.schemas.execution import ExecutionRequest
from app.schemas.flow import Flow


async def run_flow(flow_dict, inputs):
    flow = Flow.model_validate(flow_dict)
    request = ExecutionRequest.model_validate(
        {"runId": "test-run", "workflowId": "1", "flow": flow.model_dump(by_alias=True), "input": inputs}
    )
    bus = EventBus()
    runner = WorkflowRunner(request, bus, get_settings())
    await runner.run()
    events = []
    async for chunk in bus.drain():
        events.append(chunk)
    return events


def _linear_flow():
    return {
        "name": "linear",
        "nodes": [
            {"id": "start", "type": "input", "name": "开始"},
            {
                "id": "llm1",
                "type": "llm",
                "name": "写作",
                "config": {"provider": "mock", "model": "agentflow-mock", "prompt": "写一句关于 {{topic}} 的话"},
            },
            {"id": "end", "type": "output", "name": "结束", "config": {"template": "{{llm1.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm1"},
            {"id": "e2", "source": "llm1", "target": "end"},
        ],
    }


@pytest.mark.asyncio
async def test_linear_flow_emits_events():
    events = await run_flow(_linear_flow(), {"topic": "AI 工作流"})
    names = [line.split("\n")[0].removeprefix("event: ") for line in events]

    assert names[0] == "run_started"
    assert "node_started" in names
    assert "node_token" in names
    assert names[-2] == "run_finished"
    assert names[-1] == "done"

    finished = [e for e in events if e.startswith("event: run_finished")][0]
    assert '"status": "success"' in finished
    assert "AI 工作流" in finished


@pytest.mark.asyncio
async def test_condition_routes_to_true_branch():
    flow = {
        "name": "branch",
        "nodes": [
            {"id": "start", "type": "input", "name": "开始"},
            {
                "id": "gate",
                "type": "condition",
                "name": "判断",
                "config": {"expression": "input.flag == 'yes'", "trueBranch": "yes_node", "falseBranch": "no_node"},
            },
            {"id": "yes_node", "type": "template", "name": "命中", "config": {"template": "TRUE:{{input.flag}}"}},
            {"id": "no_node", "type": "template", "name": "未命中", "config": {"template": "FALSE"}},
            {"id": "end", "type": "output", "name": "结束", "config": {"template": "{{end_text}}"}},
        ],
        "edges": [
            {"source": "start", "target": "gate"},
            {"source": "yes_node", "target": "end"},
            {"source": "no_node", "target": "end"},
        ],
    }
    # output references a missing var on purpose -> value is empty, but run still succeeds
    events = await run_flow(flow, {"flag": "yes"})
    log = "".join(events)
    assert "TRUE:yes" in log
    assert "FALSE" not in log


@pytest.mark.asyncio
async def test_cycle_is_rejected():
    flow = {
        "name": "cycle",
        "nodes": [
            {"id": "a", "type": "template", "config": {"template": "a"}},
            {"id": "b", "type": "template", "config": {"template": "b"}},
        ],
        "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}],
    }
    with pytest.raises(FlowValidationError):
        validate_flow(Flow.model_validate(flow))


@pytest.mark.asyncio
async def test_unknown_node_type_rejected():
    flow = {
        "nodes": [{"id": "a", "type": "nope"}],
        "edges": [],
    }
    with pytest.raises(FlowValidationError):
        validate_flow(Flow.model_validate(flow))
