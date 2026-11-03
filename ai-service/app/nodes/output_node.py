from __future__ import annotations

from typing import Any

from app.core.template import build_names, render, render_value, stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor, extract_value
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class OutputNodeExecutor(NodeExecutor):
    type = "output"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})

        value: Any = None
        template = config.get("template")
        key = config.get("key")
        if template:
            value = render_value(template, names)
        elif key:
            value = names.get(key)
        else:
            outputs = state.get("outputs") or {}
            for node_id in reversed(state.get("executed") or []):
                if node_id != node.id and node_id in outputs:
                    value = extract_value(outputs[node_id])
                    break

        return {"value": value, "text": stringify(value), "outputKey": config.get("outputKey") or "result"}
