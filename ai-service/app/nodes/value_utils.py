"""Bounded JSON/template inputs shared by deterministic utility nodes."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from app.core.expression import evaluate
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import extract_value
from app.schemas.flow import FlowNode

MISSING = object()
MAX_ITEMS = 10_000
MAX_CHARS = 1_000_000
_EXPRESSION = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def names_for(state: FlowState) -> dict[str, Any]:
    return build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})


def render_deep(value: Any, names: dict[str, Any], depth: int = 0) -> Any:
    if depth > 32:
        raise ValueError("数据嵌套不能超过 32 层")
    if isinstance(value, dict):
        return {key: render_deep(item, names, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [render_deep(item, names, depth + 1) for item in value]
    if isinstance(value, str):
        # Mixed templates must also fail on errors, not embed error placeholders.
        match = _EXPRESSION.fullmatch(value.strip())
        if match:
            return evaluate(match.group(1), names)
        return render(value, names, strict=True)
    return value


def source_value(node: FlowNode, state: FlowState, ctx: NodeContext, key: str = "source") -> Any:
    raw = node.config.get(key, MISSING)
    if raw is MISSING or raw == "":
        outputs = state.get("outputs") or {}
        parents = [edge.source for edge in ctx.flow.incoming(node.id) if edge.source in outputs]
        value = extract_value(outputs[parents[-1]]) if parents else state.get("input") or {}
    else:
        value = render_deep(raw, names_for(state))
    check_size(value)
    return value


def _check_shape(value: Any, depth: int, budget: list[int]) -> None:
    if depth > 32:
        raise ValueError("数据嵌套不能超过 32 层")
    if isinstance(value, str) and len(value) > MAX_CHARS:
        raise ValueError("文本不能超过 1,000,000 字符")
    budget[0] += len(value) + 2 if isinstance(value, str) else 4
    if budget[0] > MAX_CHARS:
        raise ValueError("数据总大小不能超过 1,000,000 字符")
    if isinstance(value, (list, dict)):
        if len(value) > MAX_ITEMS:
            raise ValueError("集合不能超过 10,000 项")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("JSON 对象的键必须是字符串")
                _check_shape(key, depth + 1, budget)
                _check_shape(item, depth + 1, budget)
        else:
            for item in value:
                _check_shape(item, depth + 1, budget)


def check_size(value: Any) -> None:
    _check_shape(value, 0, [0])
    # Incremental encoding stops before repeated references/long CSV keys
    # could allocate an enormous serialized string just to reject it.
    size = 0
    for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False).iterencode(value):
        size += len(chunk)
        if size > MAX_CHARS:
            raise ValueError("数据总大小不能超过 1,000,000 字符")


def json_text(value: Any) -> str:
    check_size(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def parse_json(value: Any) -> Any:
    if isinstance(value, str):
        value = json.loads(value, parse_constant=_reject_constant)
    check_size(value)
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许 {value}")


def lookup(value: Any, path: str) -> Any:
    """Dot paths and RFC 6901 JSON pointers; never accesses Python attributes."""
    if not path:
        return value
    if path.startswith("/"):
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    else:
        parts = path.split(".")
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part, MISSING)
        elif isinstance(value, list) and part.isdigit():
            index = int(part)
            value = value[index] if index < len(value) else MISSING
        else:
            return MISSING
        if value is MISSING:
            return MISSING
    return value


def int_config(node: FlowNode, key: str, default: int, minimum: int, maximum: int) -> int:
    value = node.config.get(key, default)
    if isinstance(value, bool):
        raise TypeError(f"{key} 必须是整数")
    parsed = int(value)
    if isinstance(value, float) and parsed != value:
        raise ValueError(f"{key} 必须是整数")
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} 必须在 {minimum} 到 {maximum} 之间")
    return parsed


def is_number(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or (
        isinstance(value, float) and math.isfinite(value)
    )


def bool_config(node: FlowNode, key: str, default: bool) -> bool:
    value = node.config.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"{key} 必须是布尔值")
    return value
