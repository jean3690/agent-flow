from __future__ import annotations

import json
import re
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.expression import evaluate
from app.core.template import build_names, render_value, stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor, extract_value
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_OUTPUT_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_OUTPUT_KEYS = {"value", "text", "body", "audioUrl", "outputKey"}


def _render_deep(value: Any, names: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render_value(value, names)
    if isinstance(value, list):
        return [_render_deep(item, names) for item in value]
    if isinstance(value, dict):
        return {key: _render_deep(item, names) for key, item in value.items()}
    return value


@register
class OutputNodeExecutor(NodeExecutor):
    type = "output"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(
            state.get("input") or {},
            state.get("variables") or {},
            state.get("outputs") or {},
        )
        template = config.get("template")
        key = config.get("key")
        mode = str(config.get("mode") or "").strip().lower()
        if not mode:
            # 存量工作流没有 mode，沿用旧推断，保证零回归
            mode = "template" if template else "key" if key else "last"

        value: Any = None
        if mode == "template":
            value = render_value(str(template or ""), names)
        elif mode == "key":
            try:
                value = evaluate(str(key or ""), names)
            except Exception as exc:  # noqa: BLE001 - surface a readable error
                raise NodeExecutionError(node.id, f"引用变量无效: {exc}") from exc
        elif mode == "json":
            try:
                parsed = json.loads(str(template or "{}"))
            except json.JSONDecodeError as exc:
                raise NodeExecutionError(node.id, f"输出 JSON 不是合法 JSON: {exc}") from exc
            value = _render_deep(parsed, names)
        else:  # last，以及未知 mode 的兜底
            outputs = state.get("outputs") or {}
            for node_id in reversed(state.get("executed") or []):
                if node_id != node.id and node_id in outputs:
                    value = extract_value(outputs[node_id])
                    break

        raw_key = str(config.get("outputKey") or "result").strip()
        output_key = raw_key if (
            _OUTPUT_KEY_PATTERN.match(raw_key)
            and raw_key not in _RESERVED_OUTPUT_KEYS
        ) else "result"
        result: dict[str, Any] = {
            "value": value,
            "text": stringify(value),
            "outputKey": output_key,
        }
        # 加性别名：让 {{outputs["<本节点ID>"].<outputKey>}} 能取到最终值，
        # 同时保留 value/text 以不破坏 extract_value 与 _pick_output。
        result[output_key] = value
        return result
