"""JSON parsing, object mapping, list processing and declarative validation."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import (
    MAX_ITEMS,
    MISSING,
    bool_config,
    check_size,
    int_config,
    is_number,
    json_text,
    lookup,
    names_for,
    parse_json,
    render_deep,
    source_value,
)
from app.schemas.flow import FlowNode


@register
class JsonParseNodeExecutor(NodeExecutor):
    type = "json_parse"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = source_value(node, state, ctx)
        if isinstance(source, str) and bool_config(node, "stripCodeFence", True):
            text = source.strip()
            if text.startswith("```") and text.endswith("```"):
                first, separator, rest = text.partition("\n")
                if not separator or first.lower() not in {"```", "```json"}:
                    raise ValueError("仅支持完整的 JSON Markdown 代码块")
                source = rest[:-3].strip()
        data = parse_json(source)
        path = str(node.config.get("path") or "").strip()
        value = lookup(data, path)
        if value is MISSING:
            raise NodeExecutionError(node.id, f"JSON 路径不存在: {path}")
        return {"data": value, "value": value, "text": json_text(value), "type": _type_name(value)}


@register
class DataMapNodeExecutor(NodeExecutor):
    type = "data_map"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = parse_json(source_value(node, state, ctx))
        mapping = parse_json(node.config.get("mapping", "{}"))
        if not isinstance(mapping, dict):
            raise TypeError("字段映射必须是 JSON 对象")
        mapped = render_deep(mapping, {**names_for(state), "source": source})
        if bool_config(node, "mergeSource", False):
            if not isinstance(source, dict):
                raise ValueError("保留原字段时，数据源必须是对象")
            mapped = {**source, **mapped}
        if bool_config(node, "dropNull", False):
            mapped = {key: value for key, value in mapped.items() if value is not None}
        return {"data": mapped, "value": mapped, "text": json_text(mapped), "keys": list(mapped)}


def _equal(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _matches(value: Any, operator: str, expected: Any) -> bool:
    if operator == "exists":
        return value is not MISSING
    if value is MISSING:
        return False
    if operator == "eq":
        return _equal(value, expected)
    if operator == "ne":
        return not _equal(value, expected)
    if operator == "contains":
        if isinstance(value, str) and isinstance(expected, str):
            return expected in value
        if isinstance(value, list):
            return any(_equal(item, expected) for item in value)
        return False
    if operator not in {"gt", "gte", "lt", "lte"}:
        raise ValueError(f"不支持的筛选操作: {operator}")
    if not is_number(value) or not is_number(expected):
        return False
    return {"gt": value > expected, "gte": value >= expected, "lt": value < expected, "lte": value <= expected}[operator]


@register
class ListProcessNodeExecutor(NodeExecutor):
    type = "list_process"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = parse_json(source_value(node, state, ctx))
        if not isinstance(source, list):
            raise TypeError("列表处理的数据源必须是数组")
        action = str(node.config.get("action", "unique"))
        field = str(node.config.get("field") or "").strip()
        if action == "filter":
            operator = str(node.config.get("operator", "eq"))
            if operator not in {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "exists"}:
                raise ValueError(f"不支持的筛选操作: {operator}")
            expected = render_deep(node.config.get("compareValue", ""), names_for(state))
            if isinstance(expected, str):
                try:
                    expected = parse_json(expected)
                except json.JSONDecodeError:
                    pass
            result = [item for item in source if _matches(lookup(item, field), operator, expected)]
        elif action == "pluck":
            policy = str(node.config.get("missingPolicy", "null"))
            if policy not in {"null", "skip", "fail"}:
                raise ValueError("无效的缺失字段策略")
            result = []
            for item in source:
                value = lookup(item, field)
                if value is MISSING:
                    if policy == "fail":
                        raise ValueError(f"列表字段不存在: {field}")
                    if policy == "skip":
                        continue
                    value = None
                result.append(value)
        elif action == "sort":
            present = [item for item in source if lookup(item, field) is not MISSING and lookup(item, field) is not None]
            absent = [item for item in source if lookup(item, field) is MISSING or lookup(item, field) is None]
            values = [lookup(item, field) for item in present]
            if values and not (all(is_number(v) for v in values) or all(isinstance(v, str) for v in values)):
                raise ValueError("排序字段必须全部是数字或全部是字符串")
            result = sorted(present, key=lambda item: lookup(item, field), reverse=bool_config(node, "descending", False)) + absent
        elif action == "unique":
            result, seen = [], set()
            for item in source:
                value = lookup(item, field)
                if value is MISSING:
                    raise ValueError(f"去重字段不存在: {field}")
                key = json.dumps(value, sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    result.append(item)
                    seen.add(key)
        elif action == "slice":
            start = int_config(node, "start", 0, -MAX_ITEMS, MAX_ITEMS)
            end = int_config(node, "end", MAX_ITEMS, -MAX_ITEMS, MAX_ITEMS)
            result = source[start:end]
        elif action == "flatten":
            result = []
            for item in source:
                result.extend(item if isinstance(item, list) else [item])
                if len(result) > MAX_ITEMS:
                    raise ValueError("展开后的数组不能超过 10,000 项")
        else:
            raise ValueError(f"不支持的列表操作: {action}")
        return {"items": result, "value": result, "text": json_text(result), "count": len(result), "inputCount": len(source)}


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, int):
        return "integer"
    return "number"


@register
class ValidateNodeExecutor(NodeExecutor):
    type = "validate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = parse_json(source_value(node, state, ctx))
        rules = parse_json(node.config.get("rules", "{}"))
        if not isinstance(rules, dict):
            raise TypeError("校验规则必须是 JSON 对象")
        stop_on_error = bool_config(node, "stopOnError", True)
        errors = []
        for path, rule in rules.items():
            _check_rule(rule)
            value = lookup(source, path)
            messages = []
            if value is MISSING:
                if rule.get("required", False):
                    messages.append("缺少必填字段")
            else:
                kind = rule.get("type", "any")
                actual = _type_name(value)
                if kind != "any" and actual != kind and not (kind == "number" and actual == "integer"):
                    messages.append(f"类型必须为 {kind}")
                if "enum" in rule and not any(_equal(value, allowed) for allowed in rule["enum"]):
                    messages.append("不在允许值范围内")
                for key, op in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
                    if key in rule and (not is_number(value) or op(value, rule[key])):
                        messages.append(f"不满足 {key}={rule[key]}")
                for key, op in (("minLength", lambda a, b: a < b), ("maxLength", lambda a, b: a > b)):
                    if key in rule and (not isinstance(value, (str, list, dict)) or op(len(value), rule[key])):
                        messages.append(f"不满足 {key}={rule[key]}")
            errors.extend({"path": path, "message": message} for message in messages)
        check_size(errors)
        if errors and stop_on_error:
            summary = "; ".join(f"{error['path']}: {error['message']}" for error in errors[:5])
            raise NodeExecutionError(node.id, "数据校验失败: " + summary)
        return {"valid": not errors, "errors": errors, "errorCount": len(errors), "data": source, "value": source, "text": json_text(source)}


def _check_rule(rule: Any) -> None:
    allowed = {"type", "required", "enum", "min", "max", "minLength", "maxLength"}
    if not isinstance(rule, dict) or set(rule) - allowed:
        raise ValueError("校验规则仅支持 type/required/enum/min/max/minLength/maxLength")
    if rule.get("type", "any") not in {"any", "null", "boolean", "string", "array", "object", "integer", "number"}:
        raise ValueError("校验规则包含未知类型")
    if "required" in rule and not isinstance(rule["required"], bool):
        raise ValueError("required 必须是布尔值")
    if "enum" in rule and not isinstance(rule["enum"], list):
        raise ValueError("enum 必须是数组")
    for key in ("min", "max", "minLength", "maxLength"):
        if key in rule and not is_number(rule[key]):
            raise ValueError(f"{key} 必须是有限数值")
        if key.endswith("Length") and key in rule and (not isinstance(rule[key], int) or rule[key] < 0):
            raise ValueError(f"{key} 必须是非负整数")
    for low, high in (("min", "max"), ("minLength", "maxLength")):
        if low in rule and high in rule and rule[low] > rule[high]:
            raise ValueError(f"{low} 不能大于 {high}")
