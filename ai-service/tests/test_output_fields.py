import asyncio

import pytest

from app.config import Settings
from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.output_fields import apply_output_fields
from app.graph.runtime import execute_node
from app.nodes.output_node import OutputNodeExecutor
from app.schemas.flow import Flow, FlowNode


class RecordingBus:
    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))

    def close(self):
        pass


def _ctx(bus=None):
    return NodeContext(
        run_id="run-output",
        settings=Settings(mock_mode="always"),
        flow=Flow(nodes=[], edges=[]),
        bus=bus or RecordingBus(),
        subflows={},
    )


def _node(config, node_id="out"):
    return FlowNode(id=node_id, type="output", name="结束", config=config)


def _state(outputs=None, executed=None):
    return {
        "input": {"topic": "AI"},
        "variables": {},
        "outputs": outputs or {},
        "executed": executed or [],
    }


def test_no_config_returns_the_same_object():
    node = _node({})
    output = {"text": "hi", "value": "hi"}
    assert apply_output_fields(node, output) is output


def test_alias_is_added_without_touching_originals():
    node = _node({"outputFields": [{"key": "text", "alias": "summary"}]})
    original = {"text": "hello", "value": "hello", "model": "gpt"}
    result = apply_output_fields(node, original)
    assert result is not original
    assert result["text"] == "hello" and result["value"] == "hello"
    assert result["summary"] == "hello"
    assert "summary" not in original


def test_reserved_and_colliding_aliases_are_ignored():
    node = _node({"outputFields": [
        {"key": "text", "alias": "value"},
        {"key": "text", "alias": "__hidden"},
        {"key": "text", "alias": "not-valid"},
        {"key": "missing", "alias": "never"},
        {"key": "text", "alias": "model"},
    ]})
    assert set(apply_output_fields(node, {"text": "hello", "model": "gpt"})) == {"text", "model"}


def test_hidden_flag_is_a_runtime_noop():
    node = _node({"outputFields": [{"key": "text", "alias": "summary", "hidden": True}]})
    assert apply_output_fields(node, {"text": "hello"})["summary"] == "hello"


def test_output_legacy_inference_uses_template():
    out = asyncio.run(OutputNodeExecutor().execute(_node({"template": "主题 {{input.topic}}"}), _state(), _ctx()))
    assert out["value"] == "主题 AI"
    assert out["outputKey"] == "result"
    assert out["result"] == "主题 AI"
    assert out["text"] == "主题 AI"


def test_output_mode_last_takes_upstream_value():
    state = _state(outputs={"llm1": {"text": "结果"}}, executed=["llm1"])
    out = asyncio.run(OutputNodeExecutor().execute(_node({"mode": "last"}), state, _ctx()))
    assert out["value"] == "结果"


def test_output_mode_key_supports_dot_path():
    state = _state(outputs={"llm1": {"text": "结果"}}, executed=["llm1"])
    out = asyncio.run(OutputNodeExecutor().execute(
        _node({"mode": "key", "key": "outputs.llm1.text"}), state, _ctx()))
    assert out["value"] == "结果"


def test_output_mode_json_renders_nested_values():
    node = _node({"mode": "json", "template": '{"topic": "{{input.topic}}", "items": ["{{input.topic}}"]}'})
    out = asyncio.run(OutputNodeExecutor().execute(node, _state(), _ctx()))
    assert out["value"] == {"topic": "AI", "items": ["AI"]}


def test_output_invalid_json_raises_node_error():
    with pytest.raises(NodeExecutionError):
        asyncio.run(OutputNodeExecutor().execute(
            _node({"mode": "json", "template": "not json"}), _state(), _ctx()))


def test_output_reserved_key_falls_back_to_result():
    out = asyncio.run(OutputNodeExecutor().execute(
        _node({"mode": "last", "outputKey": "text"}), _state(), _ctx()))
    assert out["outputKey"] == "result"
    assert out["result"] == out["value"]
    assert "text" in out


def test_output_custom_key_is_exposed_as_alias():
    out = asyncio.run(OutputNodeExecutor().execute(
        _node({"mode": "last", "outputKey": "final"}), _state(), _ctx()))
    assert out["final"] == out["value"]


def test_execute_node_applies_aliases_to_state_and_sse():
    bus = RecordingBus()
    node = _node({"mode": "last", "outputFields": [{"key": "text", "alias": "summary"}]})
    state = _state(outputs={"llm1": {"text": "结果"}}, executed=["llm1"])
    result = asyncio.run(execute_node(node, state, _ctx(bus)))

    stored = result["outputs"]["out"]
    assert stored["text"] == "结果" and stored["summary"] == "结果"
    finished = [data for event, data in bus.events if event == "node_finished"]
    assert finished and finished[0]["output"]["summary"] == "结果"
