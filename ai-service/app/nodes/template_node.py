from __future__ import annotations

from typing import Any

from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class TemplateNodeExecutor(NodeExecutor):
    type = "template"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        template = node.config.get("template") or ""
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        text = render(template, names, strict=True)
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"渲染完成，长度 {len(text)}")
        return {"text": text}
