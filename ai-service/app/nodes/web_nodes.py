from __future__ import annotations

import json
import re
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.search import WebSearchError, tavily_search
from app.core.template import render
from app.core.web import WebFetchError, fetch_public_text
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.mcp_client import call_tool
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import names_for, parse_json, render_deep
from app.schemas.flow import FlowNode

_URL_SPLIT = re.compile(r"[,，\n\s]+")


@register
class WebFetchNodeExecutor(NodeExecutor):
    """读取公网网页并转成纯文本，支持一次抓取多个地址。"""

    type = "web_fetch"
    MAX_URLS = 5

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = names_for(state)
        raw_urls = render(str(config.get("urls") or ""), names, strict=True)
        urls = [item for item in _URL_SPLIT.split(raw_urls) if item.strip()][: self.MAX_URLS]
        if not urls:
            raise NodeExecutionError(node.id, "网页读取节点缺少 urls")

        max_chars = max(200, min(int(config.get("maxChars") or 8000), 50000))
        timeout_ms = max(1000, min(int(config.get("timeoutMs") or 15000), 60000))
        pages: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for url in urls:
            try:
                pages.append(await fetch_public_text(url, timeout_ms=timeout_ms, max_chars=max_chars))
            except WebFetchError as exc:
                failures.append({"url": url, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - one bad page should not drop the rest
                failures.append({"url": url, "error": f"抓取失败: {exc}"})

        if not pages:
            detail = failures[0]["error"] if failures else "没有可抓取的地址"
            raise NodeExecutionError(node.id, f"网页读取失败: {detail}")

        content = "\n\n".join(f"URL: {page['url']}\n{page['content']}" for page in pages)
        ctx.emit("node_log", nodeId=node.id, level="info",
                 message=f"读取 {len(pages)} 个页面" + (f"，{len(failures)} 个失败" if failures else ""))
        return {
            "pages": pages,
            "content": content,
            "text": content,
            "citations": [page["url"] for page in pages],
            "count": len(pages),
            "failures": failures,
        }


@register
class WebSearchNodeExecutor(NodeExecutor):
    """联网搜索：Tavily 直连或调用已授权的 MCP 搜索工具。"""

    type = "web_search"
    MAX_RESULTS = 10

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "tavily").strip().lower()
        names = names_for(state)
        if provider == "mcp":
            payload = await self._search_mcp(node, config, state, ctx, names)
        elif provider == "tavily":
            payload = await self._search_tavily(node, config, ctx, names)
        else:
            raise NodeExecutionError(node.id, f"不支持的搜索服务商: {provider}")

        results = _normalize_results(payload)
        summary = _summary_of(payload)
        citations = [item["url"] for item in results if item.get("url")]
        text = summary or "\n\n".join(
            f"[{index + 1}] {item.get('title', '')}\n{item.get('url', '')}\n{item.get('content', '')}"
            for index, item in enumerate(results)
        )
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"{provider} 搜索到 {len(results)} 条结果")
        return {
            "query": payload.get("query", ""),
            "provider": provider,
            "summary": summary,
            "results": results,
            "citations": citations,
            "count": len(results),
            "text": text,
        }

    async def _search_tavily(self, node: FlowNode, config: dict, ctx: NodeContext,
                             names: dict[str, Any]) -> dict[str, Any]:
        query = render(str(config.get("query") or "{{input}}"), names, strict=True).strip()
        if not query:
            raise NodeExecutionError(node.id, "联网搜索节点缺少 query")
        api_key, base_url = ctx.credentials("tavily")
        if not api_key:
            raise NodeExecutionError(node.id, "联网搜索需要先配置 Tavily API Key（模型配置页）")

        try:
            return await tavily_search(
                api_key, base_url, query,
                limit=max(1, min(int(config.get("limit") or 5), self.MAX_RESULTS)),
                freshness=str(config.get("freshness") or "").strip(),
                include_answer=bool(config.get("includeAnswer", True)),
            )
        except WebSearchError as exc:
            raise NodeExecutionError(node.id, str(exc)) from exc

    async def _search_mcp(self, node: FlowNode, config: dict, state: FlowState, ctx: NodeContext,
                          names: dict[str, Any]) -> dict[str, Any]:
        server_id = str(config.get("serverId") or "")
        server = ctx.mcp_servers.get(server_id)
        tool = str(config.get("toolName") or "")
        if not server or tool not in server.allowed_tools:
            raise NodeExecutionError(node.id, "MCP 搜索服务或工具未授权 / 已禁用")
        arguments = render_deep(parse_json(config.get("arguments", "{}")), names)
        if not isinstance(arguments, dict):
            raise NodeExecutionError(node.id, "MCP 搜索参数必须是 JSON 对象")
        try:
            result = await call_tool(server, tool, arguments, ctx.settings)
        except Exception as exc:  # noqa: BLE001 - surface as a node failure
            raise NodeExecutionError(node.id, "MCP 搜索调用失败：请检查服务状态、授权工具和参数") from exc

        text = str(result.get("text") or "").strip()
        payload: dict[str, Any] = {"query": arguments.get("query", ""), "text": text, "raw": result.get("data")}
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload.update(parsed)
            elif isinstance(parsed, list):
                payload["results"] = parsed
        if isinstance(result.get("data"), dict):
            payload.setdefault("results", result["data"].get("results"))
        return payload


def _normalize_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("results")
    if items is None and isinstance(payload.get("data"), dict):
        items = payload["data"].get("results") or payload["data"].get("items")
    if items is None:
        items = payload.get("items")
    if not isinstance(items, list):
        return []
    results: list[dict[str, Any]] = []
    for item in items[:20]:
        if isinstance(item, str):
            results.append({"title": "", "url": "", "content": item, "score": None})
            continue
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or item.get("name") or ""),
            "url": str(item.get("url") or item.get("link") or ""),
            "content": str(item.get("content") or item.get("snippet") or item.get("description") or ""),
            "score": item.get("score"),
        })
    return results


def _summary_of(payload: dict[str, Any]) -> str:
    for key in ("answer", "summary", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
