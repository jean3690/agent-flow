"""LLM 节点按提示词自动召回长期记忆（平台服务内部接口）。"""

from __future__ import annotations

from typing import Any

import httpx

from app.graph.context import NodeContext

SCOPES = {"workflow", "user", "global"}


def execution_scope(ctx: NodeContext, scope: str) -> tuple[int | None, int | None]:
    workflow_id = int(ctx.workflow_id) if str(ctx.workflow_id or "").isdigit() else None
    user_id = ctx.user_id
    if scope == "workflow" and not workflow_id:
        raise ValueError("工作流范围的记忆缺少 workflowId")
    if scope == "user" and not user_id:
        raise ValueError("用户范围的记忆缺少 userId")
    return workflow_id, user_id


async def retrieve_memory(ctx: NodeContext, *, scope: str, query: str, top_k: int = 4,
                          provider: str = "mock", model: str = "text-embedding-3-small") -> dict[str, Any]:
    if scope not in SCOPES:
        raise ValueError(f"不支持的记忆范围: {scope}")
    workflow_id, user_id = execution_scope(ctx, scope)
    base_url = ctx.settings.platform_service_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{base_url}/internal/memory/search",
            json={
                "workflowId": workflow_id,
                "userId": user_id,
                "scope": scope,
                "query": query,
                "topK": max(1, min(int(top_k), 20)),
                "provider": provider,
                "model": model,
            },
            headers={"X-Internal-Token": ctx.settings.internal_token},
        )
        response.raise_for_status()
        return (response.json() or {}).get("data") or {}
