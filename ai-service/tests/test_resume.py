import asyncio

from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.schemas.execution import ExecutionRequest
from app.schemas.flow import Flow, FlowNode


def test_execution_request_parses_resume_cache():
    request = ExecutionRequest.model_validate(
        {"flow": {"nodes": [], "edges": []}, "resume": {"tpl": {"text": "cached"}}}
    )
    assert request.resume["tpl"] == {"text": "cached"}


def test_execute_node_reuses_cached_output_without_running():
    ctx = NodeContext(
        run_id="run-resume",
        settings=Settings(mock_mode="always"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        resume_cache={"tpl": {"text": "cached"}},
    )
    node = FlowNode(id="tpl", type="template", config={"template": "这条模板不应该被执行"})
    result = asyncio.run(execute_node(node, {"input": {}}, ctx))

    assert result["outputs"]["tpl"] == {"text": "cached"}
    assert node.id in ctx.executed
