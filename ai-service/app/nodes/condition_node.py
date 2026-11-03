from __future__ import annotations

from typing import Any

from app.core.errors import NodeExecutionError
from app.core.expression import evaluate, truthy
from app.core.template import build_names
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class ConditionNodeExecutor(NodeExecutor):
    type = "condition"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        expression = config.get("expression") or "true"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        try:
            result = truthy(evaluate(expression, names))
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NodeExecutionError(node.id, f"条件求值失败: {exc}") from exc

        true_branch = config.get("trueBranch") or None
        false_branch = config.get("falseBranch") or None
        if not true_branch or not false_branch:
            derived = [edge.target for edge in ctx.flow.outgoing(node.id)]
            true_branch = true_branch or (derived[0] if derived else None)
            false_branch = false_branch or (derived[1] if len(derived) > 1 else None)

        branch = true_branch if result else false_branch
        ctx.emit(
            "node_log",
            nodeId=node.id,
            level="info",
            message=f"条件 {expression} = {result} → {branch or 'END'}",
        )
        return {"result": result, "branch": branch, "expression": expression}
