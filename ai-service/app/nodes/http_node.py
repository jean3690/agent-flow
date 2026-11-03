from __future__ import annotations

import json
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
class HttpNodeExecutor(NodeExecutor):
    type = "http"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        method = (config.get("method") or "GET").upper()
        url = render(config.get("url") or "", names, strict=True)
        if not url:
            raise NodeExecutionError(node.id, "HTTP 节点缺少 url")

        headers = {str(k): render(str(v), names) for k, v in (config.get("headers") or {}).items()}
        body = config.get("body")
        payload: Any = None
        if isinstance(body, str) and body.strip():
            rendered = render(body, names, strict=True)
            try:
                payload = json.loads(rendered)
            except json.JSONDecodeError:
                payload = rendered
        elif isinstance(body, (dict, list)):
            payload = _render_deep(body, names)

        timeout = min(120.0, max(1.0, float(config.get("timeoutMs") or 30000) / 1000))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=payload if not isinstance(payload, str) else None,
                    content=payload if isinstance(payload, str) else None,
                )
            try:
                parsed = response.json()
            except ValueError:
                parsed = response.text
            ctx.emit("node_log", nodeId=node.id, level="info", message=f"{method} {url} -> {response.status_code}")
            return {
                "status": response.status_code,
                "body": parsed,
                "headers": dict(response.headers),
            }
        except httpx.HTTPError as exc:
            raise NodeExecutionError(node.id, f"HTTP 请求失败: {exc}") from exc


def _render_deep(value: Any, names: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render(value, names)
    if isinstance(value, list):
        return [_render_deep(item, names) for item in value]
    if isinstance(value, dict):
        return {k: _render_deep(v, names) for k, v in value.items()}
    return value
