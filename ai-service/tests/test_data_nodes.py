"""Deterministic nodes: outputs, bad inputs, limits and real graph execution."""

import asyncio
import base64
import csv
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from app.catalog import node_catalog
from app.config import Settings
from app.core.errors import FlowValidationError, NodeExecutionError
from app.graph.compiler import build_graph
from app.graph.context import NodeContext
from app.graph.runtime import execute_node
from app.nodes import get_executor, registered_types
from app.nodes.value_utils import MAX_CHARS, MAX_ITEMS, MISSING, lookup, render_deep
from app.schemas.flow import Flow, FlowNode


class RecordingBus:
    def __init__(self):
        self.events = []

    def emit(self, event, **data):
        self.events.append((event, data))


def _ctx(flow=None):
    return NodeContext("data-test", Settings(mock_mode="always"), flow or Flow(), RecordingBus())


def _run(node_type, config, *, input_data=None, state=None, ctx=None):
    node = FlowNode(id="test-node", type=node_type, config=config)
    return asyncio.run(get_executor(node_type).execute(
        node, state or {"input": input_data or {}, "outputs": {}, "variables": {}}, ctx or _ctx(),
    ))


@pytest.mark.parametrize("source,expected,kind", [
    ('{"a":1,"enabled":true}', {"a": 1, "enabled": True}, "object"),
    ('```json\n[1,2]\n```', [1, 2], "array"),
    ('```\n{"a":1}\n```', {"a": 1}, "object"),
    ("false", False, "boolean"), ("0", 0, "integer"), ("1.5", 1.5, "number"),
    ('"hello"', "hello", "string"), ("null", None, "null"),
])
def test_json_parses_native_types(source, expected, kind):
    out = _run("json_parse", {"source": source})
    assert out["value"] == expected and out["type"] == kind
    assert json.loads(out["text"]) == expected


@pytest.mark.parametrize("path", ["items.0.name", "/items/0/name"])
def test_json_extracts_dot_paths_and_pointers(path):
    out = _run("json_parse", {"source": '{"items":[{"name":"中文"}]}', "path": path})
    assert out["data"] == "中文"


def test_json_pointer_handles_escaped_keys_and_null():
    assert lookup({"a/b": {"~key": None}}, "/a~1b/~0key") is None
    assert lookup({"a": None}, "a.b") is MISSING
    assert lookup([1], "-1") is MISSING
    with pytest.raises(NodeExecutionError, match="路径不存在"):
        _run("json_parse", {"source": "{}", "path": "missing"})


@pytest.mark.parametrize("source", ["not JSON", "{", "NaN", "Infinity", '```python\n{}\n```'])
def test_json_rejects_invalid_or_nonfinite_values(source):
    with pytest.raises(ValueError):
        _run("json_parse", {"source": source})


def test_source_follows_direct_upstream_not_unrelated_parallel_outputs():
    flow = Flow.model_validate({"edges": [{"source": "parent", "target": "test-node"}]})
    state = {"input": {}, "outputs": {"parent": {"value": [1, 1, 2]}, "unrelated": {"value": [9]}}}
    out = _run("list_process", {"source": "", "action": "unique"}, state=state, ctx=_ctx(flow))
    assert out["items"] == [1, 2]


def test_mapping_preserves_types_and_renders_nested_templates():
    source = {"name": "Jean", "items": [1, 2], "enabled": False}
    mapping = {"title": "{{source.name}}", "nested": {"active": "{{source.enabled}}"},
               "count": "{{len(source.items)}}", "items": "{{source.items}}", "caption": "你好 {{source.name}}"}
    out = _run("data_map", {"source": "{{input}}", "mapping": json.dumps(mapping)}, input_data=source)
    assert out["data"] == {"title": "Jean", "nested": {"active": False}, "count": 2,
                           "items": [1, 2], "caption": "你好 Jean"}
    assert source == {"name": "Jean", "items": [1, 2], "enabled": False}


def test_mapping_merges_without_mutating_source_and_can_drop_null():
    out = _run("data_map", {"source": "{{input}}", "mapping": '{"name":"new","empty":null}',
                            "mergeSource": True, "dropNull": True}, input_data={"name": "old", "count": 0})
    assert out["data"] == {"name": "new", "count": 0}


@pytest.mark.parametrize("template", ['{{missing}}', 'prefix {{missing}}', '{{missing}} suffix}}'])
def test_mapping_does_not_embed_template_errors_as_successful_data(template):
    with pytest.raises(FlowValidationError, match="未知变量"):
        _run("data_map", {"source": {}, "mapping": {"x": template}})


def test_mapping_forbids_arbitrary_code_and_private_access():
    with pytest.raises(FlowValidationError, match="安全函数"):
        render_deep("{{__import__('os')}}", {})
    with pytest.raises(FlowValidationError, match="私有属性"):
        render_deep("{{input.__class__}}", {"input": {}})


@pytest.mark.parametrize("operator,expected,names", [
    ("eq", '"active"', ["a"]), ("ne", '"active"', ["b"]),
    ("contains", '"act"', ["a", "b"]), ("exists", "", ["a", "b"]),
])
def test_list_filter_string_operators(operator, expected, names):
    source = [{"name": "a", "status": "active"}, {"name": "b", "status": "inactive"}, {"name": "c"}]
    out = _run("list_process", {"source": source, "action": "filter", "field": "status",
                                "operator": operator, "compareValue": expected})
    assert [item["name"] for item in out["items"]] == names


@pytest.mark.parametrize("operator,expected", [("gt", [9]), ("gte", [5, 9]), ("lt", [1]), ("lte", [1, 5])])
def test_list_filter_numeric_operators(operator, expected):
    out = _run("list_process", {"source": [1, 5, 9, True, "9"], "action": "filter",
                                "operator": operator, "compareValue": "5"})
    assert out["items"] == expected


def test_list_keeps_boolean_distinct_from_numeric_and_supports_array_contains():
    out = _run("list_process", {"source": [True, 1, False, 0], "action": "filter", "compareValue": "true"})
    assert out["items"] == [True]
    out = _run("list_process", {"source": [[1, 2], [3]], "action": "filter", "operator": "contains", "compareValue": "2"})
    assert out["items"] == [[1, 2]]


@pytest.mark.parametrize("policy,expected", [("null", [1, None, None]), ("skip", [1, None])])
def test_list_pluck_missing_policy(policy, expected):
    out = _run("list_process", {"source": [{"x": 1}, {}, {"x": None}], "action": "pluck", "field": "x", "missingPolicy": policy})
    assert out["items"] == expected


def test_list_pluck_can_fail_on_missing():
    with pytest.raises(ValueError, match="字段不存在"):
        _run("list_process", {"source": [{}], "action": "pluck", "field": "x", "missingPolicy": "fail"})


@pytest.mark.parametrize("descending,expected", [(False, [1, 9, None, None]), (True, [9, 1, None, None])])
def test_list_sort_is_numeric_and_puts_missing_last(descending, expected):
    out = _run("list_process", {"source": [{"x": 9}, {"x": None}, {}, {"x": 1}], "action": "sort", "field": "x", "descending": descending})
    assert [item.get("x") for item in out["items"]] == expected


def test_list_stable_unique_and_slicing_do_not_mutate_input():
    source = [{"id": 1, "n": "first"}, {"id": 1, "n": "second"}, {"id": 2}]
    out = _run("list_process", {"source": source, "action": "unique", "field": "id"})
    assert out["items"] == [source[0], source[2]]
    assert out["inputCount"] == 3 and out["count"] == 2
    assert _run("list_process", {"source": [1, 2, 3], "action": "slice", "start": -2, "end": -1})["items"] == [2]
    assert _run("list_process", {"source": [1], "action": "slice", "end": 0})["items"] == []
    assert len(source) == 3


def test_list_flatten_is_one_level_only():
    assert _run("list_process", {"source": [[1], [2, [3]], 4], "action": "flatten"})["items"] == [1, 2, [3], 4]


@pytest.mark.parametrize("action,source,extra,expected", [
    ("trim", " \n你好 \t", {}, "你好"), ("lower", "AbC", {}, "abc"), ("upper", "AbC", {}, "ABC"),
    ("replace", "aa-aa", {"search": "aa", "replacement": "b", "replaceCount": 1}, "b-aa"),
    ("replace", "aa", {"search": "a", "replacement": "b", "replaceCount": 0}, "aa"),
    ("split", "a\n\n b\n", {"removeEmpty": True}, ["a", " b"]),
    ("join", ["a", 0, False], {"separator": "|"}, "a|0|false"),
    ("truncate", "你好世界", {"maxLength": 2}, "你好"), ("truncate", "abc", {"maxLength": 0}, ""),
])
def test_text_actions(action, source, extra, expected):
    out = _run("text_process", {"source": "{{input.source}}", "action": action, **extra}, input_data={"source": source})
    assert out["value"] == expected
    assert out["truncated"] == (action == "truncate" and len(source) > len(expected))


def test_csv_handles_bom_quotes_multiline_and_unicode():
    source = '\ufeffname,note\r\n张三,"a,b"\r\n李四,"第一行\n第二行"\r\n'
    out = _run("csv", {"source": "{{input.csv}}"}, input_data={"csv": source})
    assert out["rows"] == [{"name": "张三", "note": "a,b"}, {"name": "李四", "note": "第一行\n第二行"}]
    assert out["columns"] == ["name", "note"] and out["count"] == 2


def test_csv_no_header_and_custom_delimiter():
    out = _run("csv", {"source": "a;1\nb;2", "delimiter": ";", "hasHeader": False})
    assert out["rows"] == [{"column_1": "a", "column_2": "1"}, {"column_1": "b", "column_2": "2"}]


def test_csv_roundtrip_columns_and_missing_fields():
    rows = [{"name": "张三", "note": "a,b"}, {"name": "李四"}]
    generated = _run("csv", {"source": rows, "action": "generate", "columns": ["note", "name"]})
    parsed = _run("csv", {"source": "{{input.csv}}"}, input_data={"csv": generated["text"]})
    assert parsed["rows"] == [{"note": "a,b", "name": "张三"}, {"note": "", "name": "李四"}]


@pytest.mark.parametrize("protect,prefix", [(True, "'"), (False, "")])
def test_csv_export_protects_formula_cells_and_header_but_not_numbers(protect, prefix):
    out = _run("csv", {"source": [{"=header": "  =SUM(A1)", "number": -1}], "action": "generate", "protectFormulas": protect})
    assert out["text"].startswith(prefix + "=header,number")
    assert prefix + "  =SUM(A1),-1" in out["text"]


@pytest.mark.parametrize("source,config", [("a,a\n1,2", {}), ("a,b\n1", {}), ('a\n"unclosed', {}),
                                          ("a,b\n1,2", {"columns": ["x", "y"]})])
def test_csv_rejects_ambiguous_or_malformed_rows(source, config):
    with pytest.raises((ValueError, csv.Error)):
        _run("csv", {"source": source, **config})


def test_datetime_formats_epoch_zero_and_converts_zones():
    out = _run("date_time", {"source": 0, "action": "format", "timezone": "Asia/Shanghai"})
    assert out["text"] == "1970-01-01 08:00:00" and out["timestamp"] == 0
    assert _run("date_time", {"source": "2025/01/02", "action": "format", "inputFormat": "%Y/%m/%d", "timezone": "UTC"})["iso"].startswith("2025-01-02T00:00:00")


def test_datetime_add_and_diff_account_for_dst_elapsed_time():
    out = _run("date_time", {"source": "2025-03-09T01:30:00-05:00", "action": "add", "offset": 1, "unit": "hours", "timezone": "America/New_York"})
    assert out["iso"] == "2025-03-09T03:30:00-04:00"
    out = _run("date_time", {"source": "2025-03-09T01:30:00", "end": "2025-03-09T03:30:00", "action": "diff", "timezone": "America/New_York"})
    assert out["differenceSeconds"] == 3600 and out["value"] == 3600


def test_datetime_now_has_requested_timezone():
    before = datetime.now(UTC).timestamp()
    out = _run("date_time", {"action": "now", "timezone": "UTC"})
    assert before <= out["timestamp"] <= datetime.now(UTC).timestamp()
    assert out["iso"].endswith("+00:00")


@pytest.mark.parametrize("config", [
    {"timezone": "No/SuchZone"}, {"action": "format", "source": "not-a-date"},
    {"action": "format", "source": "2025-03-09T02:30:00", "timezone": "America/New_York"},
    {"action": "add", "source": "2025-01-01", "offset": 50000, "unit": "days"},
    {"action": "diff", "source": "2025-01-01"},
    {"action": "unknown"},
])
def test_datetime_rejects_invalid_configuration(config):
    with pytest.raises(ValueError):
        _run("date_time", config)


def test_validation_supports_required_types_ranges_lengths_enums_and_nested_paths():
    source = {"user": {"name": "Jean", "age": 20}, "tags": ["a"], "enabled": False}
    rules = {"user.name": {"required": True, "type": "string", "minLength": 1},
             "user.age": {"type": "integer", "min": 0, "max": 100},
             "tags": {"type": "array", "maxLength": 2}, "enabled": {"type": "boolean", "enum": [False]}}
    out = _run("validate", {"source": source, "rules": rules})
    assert out["valid"] is True and out["errors"] == [] and out["value"] == source


def test_validation_returns_structured_errors_or_fails_the_node():
    config = {"source": {"age": True, "name": ""}, "rules": {"email": {"required": True},
              "age": {"type": "integer"}, "name": {"minLength": 1}}, "stopOnError": False}
    out = _run("validate", config)
    assert out["valid"] is False and out["errorCount"] == 3
    assert {error["path"] for error in out["errors"]} == {"age", "name", "email"}
    with pytest.raises(NodeExecutionError, match="数据校验失败"):
        _run("validate", {**config, "stopOnError": True})


@pytest.mark.parametrize("rule", [{"type": "email"}, {"pattern": ".*"}, {"enum": "abc"},
                                  {"required": "yes"}, {"minLength": -1}, {"min": 10, "max": 1}])
def test_validation_rejects_invalid_rules_even_when_field_absent(rule):
    with pytest.raises(ValueError):
        _run("validate", {"source": {}, "rules": {"x": rule}, "stopOnError": False})


@pytest.mark.parametrize("encode,decode", [("base64_encode", "base64_decode"), ("url_encode", "url_decode")])
def test_encoding_roundtrips_unicode(encode, decode):
    value = "中文 🎉/?a=1&b=2+3"
    encoded = _run("encode", {"source": value, "action": encode})["text"]
    assert _run("encode", {"source": encoded, "action": decode})["text"] == value


def test_hashes_have_known_sha256_and_sha512_outputs():
    out = _run("encode", {"source": "abc", "action": "sha256"})
    assert out["text"] == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(_run("encode", {"source": "abc", "action": "sha512"})["text"]) == 128


@pytest.mark.parametrize("action,source", [("base64_decode", "invalid!!"), ("base64_decode", "/w=="), ("url_decode", "%FF"), ("url_decode", "%ZZ")])
def test_encoding_rejects_invalid_or_binary_text(action, source):
    with pytest.raises(ValueError):
        _run("encode", {"source": source, "action": action})


@pytest.mark.parametrize("node_type,config", [
    ("json_parse", {"source": "x" * (MAX_CHARS + 1)}),
    ("list_process", {"source": list(range(MAX_ITEMS + 1))}),
    ("text_process", {"source": "a" * 1000, "action": "replace", "search": "a", "replacement": "x" * 2000}),
    ("text_process", {"source": ["a"] * 100, "action": "join", "separator": "x" * 20000}),
    ("text_process", {"source": "a," * MAX_ITEMS, "action": "split", "separator": ","}),
])
def test_limits_reject_oversized_inputs_and_expansion(node_type, config):
    with pytest.raises(ValueError, match="超过|限制"):
        _run(node_type, config)


def test_serialized_size_limit_rejects_repeated_large_keys_without_full_allocation():
    with pytest.raises(ValueError, match="数据总大小"):
        _run("csv", {"source": "x" * 10000 + "\n" + "a\n" * 200})


@pytest.mark.parametrize("node_type,config", [
    ("list_process", {"source": {}, "action": "sort"}),
    ("list_process", {"source": [1, "2"], "action": "sort"}),
    ("list_process", {"source": [], "action": "unknown"}),
    ("data_map", {"source": {}, "mapping": []}),
    ("text_process", {"source": "abc", "action": "split", "separator": ""}),
    ("text_process", {"source": "abc", "action": "replace", "search": ""}),
    ("csv", {"source": "a", "delimiter": ",;"}),
    ("encode", {"source": 12}),
])
def test_invalid_inputs_fail_instead_of_silent_fallback(node_type, config):
    with pytest.raises((TypeError, ValueError)):
        _run(node_type, config)


def test_every_new_executor_has_identical_declared_output_fields_and_defaults():
    types = {"json_parse", "data_map", "list_process", "text_process", "csv", "date_time", "validate", "encode"}
    assert types <= set(registered_types())
    configs = {
        "json_parse": {"source": "{}"}, "data_map": {"source": {}}, "list_process": {"source": []},
        "text_process": {"source": "hello"}, "csv": {"source": "a\n1"}, "date_time": {},
        "validate": {"source": {}}, "encode": {"source": "abc"},
    }
    for definition in node_catalog():
        if definition["type"] not in types:
            continue
        config = {field["key"]: field["default"] for field in definition["configSchema"] if "default" in field}
        config.update(configs[definition["type"]])
        output = _run(definition["type"], config)
        assert set(output) == {field["key"] for field in definition["configSchema"][-1]["fields"]}


def test_new_catalog_metadata_exactly_matches_java_and_has_no_duplicate_types():
    path = Path(__file__).resolve().parents[2] / "platform-service/app/resources/node-definitions.json"
    java = {node["type"]: node for node in json.loads(path.read_text())}
    python = node_catalog()
    assert len(python) == len({node["type"] for node in python})
    assert {node["type"] for node in python} == set(registered_types())
    for node in python:
        if node["type"] in {"json_parse", "data_map", "list_process", "text_process", "csv", "date_time", "validate", "encode"}:
            assert node == java[node["type"]]


def test_failure_policy_and_output_aliases_work_for_new_nodes():
    node = FlowNode(id="bad", type="validate", config={"source": {}, "rules": {"x": {"required": True}}, "onError": "continue"})
    out = asyncio.run(execute_node(node, {"input": {}}, _ctx()))
    assert out["outputs"]["bad"]["failed"] is True
    node = FlowNode(id="good", type="json_parse", config={"source": "[1]", "outputFields": [{"key": "data", "alias": "rows"}]})
    out = asyncio.run(execute_node(node, {"input": {}}, _ctx()))
    assert out["outputs"]["good"]["rows"] == [1]


def test_all_eight_nodes_execute_in_a_real_langgraph_chain():
    specs = [
        ("start", "input", {}),
        ("parsed", "json_parse", {"source": "{{input.raw}}"}),
        ("filtered", "list_process", {"action": "filter", "field": "active", "compareValue": "true"}),
        ("table", "csv", {"action": "generate", "columns": ["name", "email"]}),
        ("clean", "text_process", {"action": "trim"}),
        ("encoded", "encode", {"action": "base64_encode"}),
        ("clock", "date_time", {"action": "now", "timezone": "UTC"}),
        ("mapped", "data_map", {"source": {}, "mapping": {
            "count": '{{outputs["filtered"].count}}', "archive": '{{outputs["encoded"].text}}',
            "generatedAt": '{{outputs["clock"].iso}}',
        }}),
        ("checked", "validate", {"rules": {"count": {"type": "integer", "min": 1}, "archive": {"type": "string", "minLength": 1}}}),
        ("end", "output", {}),
    ]
    flow = Flow.model_validate({
        "nodes": [{"id": node_id, "type": node_type, "config": config} for node_id, node_type, config in specs],
        "edges": [{"source": left[0], "target": right[0]} for left, right in pairwise(specs)],
    })
    ctx = _ctx(flow)
    raw = json.dumps([{"name": "张三", "email": "a@example.com", "active": True}, {"name": "李四", "active": False}])
    result = asyncio.run(build_graph(flow, ctx).ainvoke({"input": {"raw": raw}, "outputs": {}, "variables": {}, "executed": []}))
    final = result["outputs"]["end"]["value"]
    assert final["count"] == 1
    assert base64.b64decode(final["archive"]).decode() == "name,email\r\n张三,a@example.com"
    assert len(result["outputs"]) == len(specs)
    assert sum(event == "node_finished" for event, _ in ctx.bus.events) == len(specs)


def test_documented_data_export_workflow_runs_as_published():
    path = Path(__file__).resolve().parents[2] / "docs/examples/data-export.flow.json"
    flow = Flow.model_validate(json.loads(path.read_text()))
    raw = json.dumps([{"name": "张三", "score": 92}, {"name": "李四", "score": 60}, {"name": "王五", "score": 85}])
    result = asyncio.run(build_graph(flow, _ctx(flow)).ainvoke({"input": {"raw": raw}, "outputs": {}, "executed": [], "variables": {}}))
    output = result["outputs"]["end"]["value"]
    assert output == {"count": 2, "rows": [{"name": "张三", "score": 92}, {"name": "王五", "score": 85}],
                      "csv": "name,score\r\n张三,92\r\n王五,85\r\n"}
