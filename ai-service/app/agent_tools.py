from __future__ import annotations

import html as html_lib
import ipaddress
import json
import re
import socket
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from app.skills.registry import get_skill_registry

if TYPE_CHECKING:
    from app.graph.context import NodeContext
    from app.graph.state import FlowState

MAX_FETCH_CHARS = 4000

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_input",
            "description": "读取本次运行的输入参数（JSON）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": "按名称加载技能正文，用于获取领域指令",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "技能名称"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "在当前挂载的知识库中检索相关片段",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索语句"},
                    "top_k": {"type": "integer", "description": "返回片段数，默认 4"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "抓取一个公开网页并返回纯文本内容（仅支持公网 http/https）",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "完整 URL"}},
                "required": ["url"],
            },
        },
    },
]

TOOL_LABELS = {
    "read_input": "读取输入",
    "load_skill": "加载技能",
    "knowledge_search": "知识检索",
    "web_fetch": "网页抓取",
}


async def execute_tool(name: str, args: dict[str, Any], state: FlowState,
                       ctx: NodeContext, config: dict[str, Any]) -> str:
    if name == "read_input":
        return json.dumps(state.get("input") or {}, ensure_ascii=False)[:MAX_FETCH_CHARS]
    if name == "load_skill":
        skill = str(args.get("name") or "").strip()
        if not skill:
            return "错误：缺少技能名称"
        try:
            detail = get_skill_registry().detail(skill)
        except Exception as exc:  # noqa: BLE001 - tool errors are returned to the model
            return f"错误：{exc}"
        return f"{detail['title']}\n{detail['content']}"[:MAX_FETCH_CHARS]
    if name == "knowledge_search":
        return await _knowledge_search(args, config, ctx)
    if name == "web_fetch":
        return await _web_fetch(str(args.get("url") or ""))
    return f"错误：未知工具 {name}"


async def _knowledge_search(args: dict[str, Any], config: dict[str, Any], ctx: NodeContext) -> str:
    knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
    if not knowledge_base_id:
        return "错误：节点未挂载知识库"
    query = str(args.get("query") or "").strip()
    if not query:
        return "错误：缺少检索语句"
    top_k = int(args.get("top_k") or 4)
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
    except Exception as exc:  # noqa: BLE001 - surface as tool result
        return f"错误：知识库检索失败 {exc}"
    chunks = data.get("chunks") or []
    if not chunks:
        return "知识库中没有检索到相关内容"
    return "\n\n".join(
        f"[{index + 1}] {item.get('title', '')} (score {item.get('score', 0)})\n{item.get('content', '')}"
        for index, item in enumerate(chunks)
    )[:MAX_FETCH_CHARS]


async def _web_fetch(url: str) -> str:
    if not url:
        return "错误：缺少 url"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "错误：仅支持 http/https 公网地址"
    reason = _blocked_reason(parsed.hostname)
    if reason:
        return f"错误：{reason}"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "AgentFlow/0.1"})
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            text = response.text
    except Exception as exc:  # noqa: BLE001 - surface as tool result
        return f"错误：抓取失败 {exc}"
    if "html" in content_type or text.lstrip().startswith("<"):
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_FETCH_CHARS]


def _blocked_reason(hostname: str) -> str | None:
    lowered = hostname.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return "不允许访问内网地址"
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except socket.gaierror:
        return None
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return "不允许访问内网地址"
    return None
