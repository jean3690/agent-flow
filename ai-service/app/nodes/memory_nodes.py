from __future__ import annotations

from typing import Any

import httpx

from app.core.errors import NodeExecutionError
from app.core.template import render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import names_for
from app.schemas.flow import FlowNode

_SCOPES = {"workflow", "user", "global"}
_MEMORY_TYPES = {"fact", "preference", "decision", "summary", "other"}
_MAX_TAGS = 10


def _scope(value: Any) -> str:
    scope = str(value or "workflow").strip().lower()
    return scope if scope in _SCOPES else "workflow"


def _tags(value: Any) -> list[str]:
    items = value if isinstance(value, list) else str(value or "").replace("，", ",").split(",")
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text[:32])
    return result[:_MAX_TAGS]


async def _post_internal(ctx: NodeContext, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base_url = ctx.settings.java_service_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{base_url}{path}",
            json=payload,
            headers={"X-Internal-Token": ctx.settings.internal_token},
        )
        response.raise_for_status()
        return (response.json() or {}).get("data") or {}


def _execution_context(ctx: NodeContext, scope: str) -> tuple[Any, Any]:
    workflow_id = int(ctx.workflow_id) if str(ctx.workflow_id or "").isdigit() else None
    user_id = ctx.user_id
    if scope == "workflow" and not workflow_id:
        raise NodeExecutionError("", "记忆范围是工作流，但当前执行缺少工作流 ID")
    if scope == "user" and not user_id:
        raise NodeExecutionError("", "记忆范围是用户，但当前执行缺少用户 ID")
    return workflow_id, user_id


@register
class MemoryWriteNodeExecutor(NodeExecutor):
    """把一条事实写入长期记忆，范围由 workflow / user / global 决定。"""

    type = "memory_write"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = names_for(state)
        content = render(str(config.get("content") or "{{input}}"), names, strict=True).strip()
        if not content:
            raise NodeExecutionError(node.id, "写入记忆节点缺少 content")
        if len(content) > 8000:
            raise NodeExecutionError(node.id, "记忆内容不能超过 8000 字")

        scope = _scope(config.get("scope"))
        memory_type = str(config.get("memoryType") or "fact").strip().lower()
        if memory_type not in _MEMORY_TYPES:
            memory_type = "fact"
        try:
            workflow_id, user_id = _execution_context(ctx, scope)
        except NodeExecutionError as exc:
            raise NodeExecutionError(node.id, exc.message) from exc

        payload = {
            "workflowId": workflow_id,
            "userId": user_id,
            "scope": scope,
            "memoryType": memory_type,
            "content": content,
            "tags": _tags(config.get("tags")),
            "sourceNodeId": node.id,
            "provider": str(config.get("provider") or "mock"),
            "model": str(config.get("model") or "text-embedding-3-small"),
        }
        try:
            data = await _post_internal(ctx, "/internal/memory/write", payload)
        except Exception as exc:  # noqa: BLE001 - memory writes surface as node failures
            raise NodeExecutionError(node.id, f"写入记忆失败: {exc}") from exc

        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"已写入 {scope} 记忆 {str(data.get('memoryId') or '')}".strip())
        return {
            "memoryId": data.get("memoryId"),
            "scope": data.get("scope", scope),
            "memoryType": memory_type,
            "stored": bool(data.get("stored")),
            "text": content,
        }


@register
class MemoryRetrieveNodeExecutor(NodeExecutor):
    """按语义 / 词法相似度召回长期记忆，输出可直接拼进提示词的 context。"""

    type = "memory_retrieve"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = names_for(state)
        query = render(str(config.get("query") or "{{input}}"), names, strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "召回记忆节点缺少 query")

        scope = _scope(config.get("scope"))
        try:
            workflow_id, user_id = _execution_context(ctx, scope)
        except NodeExecutionError as exc:
            raise NodeExecutionError(node.id, exc.message) from exc

        payload = {
            "workflowId": workflow_id,
            "userId": user_id,
            "scope": scope,
            "query": query,
            "tags": _tags(config.get("tags")),
            "topK": max(1, min(int(config.get("topK") or 5), 20)),
            "provider": str(config.get("provider") or "mock"),
            "model": str(config.get("model") or "text-embedding-3-small"),
        }
        try:
            data = await _post_internal(ctx, "/internal/memory/search", payload)
        except Exception as exc:  # noqa: BLE001 - retrieval failures surface as node failures
            raise NodeExecutionError(node.id, f"召回记忆失败: {exc}") from exc

        memories = data.get("memories") or []
        context = str(data.get("context") or "")
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"召回 {len(memories)} 条 {scope} 记忆")
        return {
            "query": query,
            "scope": scope,
            "memories": memories,
            "context": context,
            "text": context,
            "citations": [item.get("memoryId") for item in memories if item.get("memoryId")],
            "count": len(memories),
        }
