from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from app.core.search import WebSearchError, tavily_search
from app.core.storage import StorageError, list_files, read_text, save_text
from app.core.web import WebFetchError, blocked_reason, fetch_public_text
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
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索公开信息，返回标题、链接与摘要（需配置 Tavily Key）",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索语句"},
                    "limit": {"type": "integer", "description": "结果条数，默认 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "读取工作区存储目录内的文本文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对存储目录的文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "把文本写入工作区存储目录（自动校验路径，禁止越界）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对存储目录的文件路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                    "append": {"type": "boolean", "description": "是否追加写入，默认 false"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "列出工作区存储目录内的文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "可选的路径前缀"},
                    "limit": {"type": "integer", "description": "最多返回数量，默认 50"},
                },
            },
        },
    },
]

TOOL_LABELS = {
    "read_input": "读取输入",
    "load_skill": "加载技能",
    "knowledge_search": "知识检索",
    "web_fetch": "网页抓取",
    "web_search": "联网搜索",
    "file_read": "读取文件",
    "file_write": "写入文件",
    "file_list": "文件列表",
}


async def execute_tool(name: str, args: dict[str, Any], state: FlowState,
                       ctx: NodeContext, config: dict[str, Any]) -> str:
    if name == "read_input":
        return json.dumps(state.get("input") or {}, ensure_ascii=False)[:MAX_FETCH_CHARS]
    if name == "load_skill":
        skill = str(args.get("name") or "").strip()
        if not skill:
            return "错误：缺少技能名称"
        if "skillIds" in config and skill not in (config.get("skillIds") or []):
            return "错误：该技能未挂载到当前智能体"
        try:
            detail = get_skill_registry().detail(skill)
        except Exception as exc:  # noqa: BLE001 - tool errors are returned to the model
            return f"错误：{exc}"
        return f"{detail['title']}\n{detail['content']}"[:MAX_FETCH_CHARS]
    if name == "knowledge_search":
        return await _knowledge_search(args, config, ctx)
    if name == "web_fetch":
        return await _web_fetch(str(args.get("url") or ""))
    if name == "web_search":
        return await _web_search(args, ctx)
    if name == "file_read":
        return _file_read(args, ctx)
    if name == "file_write":
        return _file_write(args, ctx)
    if name == "file_list":
        return _file_list(args, ctx)
    return f"错误：未知工具 {name}"


async def _web_search(args: dict[str, Any], ctx: NodeContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return "错误：缺少检索语句"
    api_key, base_url = ctx.credentials("tavily")
    if not api_key:
        return "错误：未配置 Tavily 搜索 Key，请在「模型配置」页填写"
    try:
        limit = max(1, min(int(args.get("limit") or 5), 10))
    except (TypeError, ValueError):
        limit = 5
    try:
        data = await tavily_search(api_key, base_url, query, limit=limit)
    except WebSearchError as exc:
        return f"错误：{exc}"
    results = data.get("results") or []
    if not results:
        return str(data.get("answer") or "没有搜索到结果")[:MAX_FETCH_CHARS]
    lines = []
    for index, item in enumerate(results[:limit]):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"[{index + 1}] {item.get('title', '')}\n{item.get('url', '')}\n{item.get('content', '')}"
        )
    summary = str(data.get("answer") or "").strip()
    text = (summary + "\n\n" if summary else "") + "\n\n".join(lines)
    return text[:MAX_FETCH_CHARS]


def _file_read(args: dict[str, Any], ctx: NodeContext) -> str:
    path = str(args.get("path") or "").strip()
    if not path:
        return "错误：缺少文件路径"
    try:
        result = read_text(ctx.settings, path, max_chars=MAX_FETCH_CHARS)
    except StorageError as exc:
        return f"错误：{exc}"
    return result["text"][:MAX_FETCH_CHARS]


def _file_write(args: dict[str, Any], ctx: NodeContext) -> str:
    path = str(args.get("path") or "").strip()
    content = str(args.get("content") or "")
    if not path:
        return "错误：缺少文件路径"
    try:
        metadata = save_text(
            ctx.settings,
            content,
            name=path,
            overwrite=True,
            append=bool(args.get("append")),
        )
    except StorageError as exc:
        return f"错误：{exc}"
    return json.dumps(metadata, ensure_ascii=False)


def _file_list(args: dict[str, Any], ctx: NodeContext) -> str:
    try:
        limit = max(1, min(int(args.get("limit") or 50), 500))
    except (TypeError, ValueError):
        limit = 50
    try:
        items = list_files(ctx.settings, prefix=str(args.get("prefix") or ""), limit=limit)
    except StorageError as exc:
        return f"错误：{exc}"
    return json.dumps(items[:limit], ensure_ascii=False)[:MAX_FETCH_CHARS]


async def _knowledge_search(args: dict[str, Any], config: dict[str, Any], ctx: NodeContext) -> str:
    knowledge_base_id = str(config.get("knowledgeBaseId") or "").strip()
    if not knowledge_base_id:
        return "错误：节点未挂载知识库"
    query = str(args.get("query") or "").strip()
    if not query:
        return "错误：缺少检索语句"
    top_k = int(args.get("top_k") or 4)
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
    try:
        page = await fetch_public_text(url, max_chars=MAX_FETCH_CHARS)
    except WebFetchError as exc:
        return f"错误：{exc}"
    except Exception as exc:  # noqa: BLE001 - surface as tool result
        return f"错误：抓取失败 {exc}"
    return page["content"]


def _blocked_reason(hostname: str) -> str | None:
    """保留旧入口，实际校验逻辑在 app.core.web。"""
    return blocked_reason(hostname)
