"""Tavily 联网搜索客户端，web_search 节点与智能体工具共用。"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.tavily.com"


class WebSearchError(ValueError):
    """搜索失败；消息可直接展示给用户。"""


async def tavily_search(api_key: str, base_url: str | None, query: str, *,
                        limit: int = 5, freshness: str = "",
                        include_answer: bool = True, timeout: float = 30) -> dict[str, Any]:
    if not api_key:
        raise WebSearchError("未配置 Tavily API Key")
    clean_query = (query or "").strip()
    if not clean_query:
        raise WebSearchError("检索语句不能为空")

    body: dict[str, Any] = {
        "query": clean_query,
        "max_results": max(1, min(int(limit), 10)),
        "include_answer": bool(include_answer),
        "search_depth": "basic",
    }
    if freshness:
        body["topic"] = "general"
        body["time_range"] = freshness

    base = (base_url or DEFAULT_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                f"{base}/search",
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise WebSearchError(f"联网搜索失败: {exc}") from exc
    if not isinstance(data, dict):
        raise WebSearchError("联网搜索返回格式不正确")
    data.setdefault("query", clean_query)
    return data
