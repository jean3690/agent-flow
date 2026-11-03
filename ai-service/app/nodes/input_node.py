from __future__ import annotations

from typing import Any

from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class InputNodeExecutor(NodeExecutor):
    type = "input"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        data = state.get("input") or {}
        variables = node.config.get("variables") or []
        if variables:
            missing = [name for name in variables if name not in data]
            if missing:
                ctx.emit("node_log", nodeId=node.id, level="warn", message=f"缺少输入变量: {', '.join(missing)}")
        result: dict[str, Any] = {"value": data}
        if isinstance(data, dict):
            result.update({k: v for k, v in data.items() if k not in result})
        return result
