from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class KnowledgeNodeExecutor(NodeExecutor):
    """Retrieve chunks from a knowledge base owned by the Java service."""

    type = "knowledge"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
        if not knowledge_base_id:
            raise NodeExecutionError(node.id, "知识检索节点未选择知识库")

        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        query = render(config.get("query") or "{{input}}", names, strict=True)
        top_k = int(config.get("topK") or 4)

        base_url = ctx.settings.java_service_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{base_url}/internal/knowledge/search",
                    json={"knowledgeBaseId": knowledge_base_id, "query": query, "topK": top_k},
                    headers={"X-Internal-Token": ctx.settings.internal_token},
                )
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
        except Exception as exc:  # noqa: BLE001 - node failures are surfaced through SSE
            raise NodeExecutionError(node.id, f"知识库检索失败: {exc}") from exc

        chunks = data.get("chunks") or []
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"检索到 {len(chunks)} 个片段")
        return {
            "text": "\n\n".join(str(item.get("content", "")) for item in chunks),
            "chunks": chunks,
            "count": len(chunks),
            "knowledgeBaseId": knowledge_base_id,
            "query": query,
        }
