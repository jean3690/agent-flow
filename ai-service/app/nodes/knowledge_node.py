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
    """Retrieve chunks from a knowledge base owned by the platform service."""

    type = "knowledge"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
        if not knowledge_base_id:
            raise NodeExecutionError(node.id, "知识检索节点未选择知识库")

        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        query = render(config.get("query") or "{{input}}", names, strict=True)
        top_k = int(config.get("topK") or 4)

        base_url = ctx.settings.platform_service_base_url.rstrip("/")
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


@register
class KnowledgeUpsertNodeExecutor(NodeExecutor):
    """把运行期内容写入知识库并立即建索引；同标题覆盖，可用于沉淀执行结果。"""

    type = "knowledge_upsert"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
        if not knowledge_base_id:
            raise NodeExecutionError(node.id, "知识写入节点未选择知识库")

        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        title = render(str(config.get("title") or ""), names).strip()
        content = render(str(config.get("content") or "{{input}}"), names, strict=True).strip()
        if not content:
            raise NodeExecutionError(node.id, "知识写入内容不能为空")

        base_url = ctx.settings.platform_service_base_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{base_url}/internal/knowledge/upsert",
                    json={"knowledgeBaseId": knowledge_base_id, "title": title, "content": content},
                    headers={"X-Internal-Token": ctx.settings.internal_token},
                )
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
        except Exception as exc:  # noqa: BLE001 - node failures are surfaced through SSE
            raise NodeExecutionError(node.id, f"知识写入失败: {exc}") from exc

        status = str(data.get("status") or "")
        if status != "INDEXED":
            detail = str(data.get("errorMessage") or status or "未知错误")
            raise NodeExecutionError(node.id, f"知识写入未完成索引: {detail}")

        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"已写入知识库文档 {data.get('title')}（{data.get('chunkCount', 0)} 个分片）")
        return {
            "documentId": data.get("id"),
            "title": data.get("title"),
            "status": status,
            "chunkCount": data.get("chunkCount", 0),
            "knowledgeBaseId": knowledge_base_id,
            "text": content,
        }
