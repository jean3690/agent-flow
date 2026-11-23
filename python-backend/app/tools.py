from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from . import agent_plan, knowledge, mcp
from .db import first_text, to_float, to_int
from .skills import skill_registry

logger = logging.getLogger("paiagent.tools")

MAX_PAGE_CHARS = 8000


@dataclass
class ToolContext:
    db: Session
    node_id: str
    node_type: str
    node_data: dict
    current_input: dict


class AgentTool:
    name = ""
    description = ""
    input_schema = "{}"

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        raise NotImplementedError


class ReadCurrentInputTool(AgentTool):
    name = "read_current_input"
    description = "读取当前 ReAct 节点收到的输入数据。适合在需要确认上游节点输出结构时调用。"
    input_schema = '{"type":"object","properties":{}}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        return {"currentInput": context.current_input}


class KnowledgeRetrieveTool(AgentTool):
    name = "knowledge_retrieve"
    description = "从当前节点配置的知识库中检索与问题相关的项目资料、实现计划、字段和节点说明。"
    input_schema = '{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        query = str(arguments.get("query", ""))
        knowledge_base_id = first_text(
            arguments.get("knowledgeBaseId"),
            context.node_data.get("knowledgeBaseId"),
            "default",
        ) or "default"
        top_k = to_int(context.node_data.get("knowledgeTopK"), None)
        if top_k is None:
            top_k = to_int(arguments.get("topK"), 5) or 5
        threshold = to_float(context.node_data.get("knowledgeScoreThreshold"), None)
        if threshold is None:
            threshold = to_float(arguments.get("scoreThreshold"), 0.2)
        if threshold is None:
            threshold = 0.2
        return knowledge.search_runtime(context.db, knowledge_base_id, query, top_k, threshold)


class MemoryRetrieveTool(AgentTool):
    name = "memory_retrieve"
    description = "从 Agent 长期记忆中召回与当前任务相关的偏好、背景和历史结论。"
    input_schema = '{"type":"object","properties":{"query":{"type":"string"},"scope":{"type":"string"},"topK":{"type":"number"}},"required":["query"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        query = str(arguments.get("query", ""))
        scope = str(arguments.get("scope", "workflow"))
        top_k = to_int(arguments.get("topK"), 5) or 5
        config = agent_plan.resolve(context.db, context.node_data, "memory")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, query)
        return agent_plan.memory_service.retrieve(query, scope, [], embedding, top_k)


class MemoryWriteTool(AgentTool):
    name = "memory_write"
    description = "显式写入 Agent 长期记忆，适合保存用户偏好、项目背景和稳定结论。"
    input_schema = '{"type":"object","properties":{"content":{"type":"string"},"memoryType":{"type":"string"},"scope":{"type":"string"},"tags":{"type":"string"}},"required":["content"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        content = str(arguments.get("content", ""))
        scope = str(arguments.get("scope", "workflow"))
        memory_type = str(arguments.get("memoryType", "fact"))
        tags_text = str(arguments.get("tags", ""))
        config = agent_plan.resolve(context.db, context.node_data, "memory")
        embedding: list[float] = []
        if config.api_url and config.api_key and config.model:
            embedding = agent_plan.agent_plan_client.create_embedding(config, content)
        return agent_plan.memory_service.write(
            content,
            memory_type,
            scope,
            agent_plan.memory_service.split_tags(tags_text),
            context.node_id,
            embedding,
            config.model,
        )


class WebSearchTool(AgentTool):
    name = "web_search"
    description = "通过 Agent Plan Harness 联网搜索 MCP 获取实时、权威信息。"
    input_schema = '{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"number"}},"required":["query"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        query = str(arguments.get("query", ""))
        limit = to_int(arguments.get("limit"), 5) or 5
        selected = mcp.resolve_first_enabled_web_search(context.db, context.node_data.get("mcpToolIds"))
        if selected is None:
            raise ValueError("联网搜索工具未配置，请先在 MCP 工具中添加 Agent Plan 联网搜索，并在当前大模型节点选择它")
        result = mcp.web_search(selected, query, limit, None, None, "web")
        return {
            "summary": result.get("summary"),
            "results": result.get("results"),
            "citations": result.get("citations"),
        }


def _resolve_urls(arguments: dict) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        for item in re.split(r"[,，\n\s]+", str(value)):
            trimmed = item.strip()
            if trimmed:
                urls.append(trimmed)

    urls_value = arguments.get("urls")
    if isinstance(urls_value, list):
        for item in urls_value:
            add(item)
    else:
        add(urls_value)
    add(arguments.get("url"))
    deduped: list[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


class WebFetchTool(AgentTool):
    name = "web_fetch"
    description = "读取指定 URL 的网页内容，用于搜索结果后的原文核验和信息抽取。"
    input_schema = '{"type":"object","properties":{"urls":{"type":"array","items":{"type":"string"}},"url":{"type":"string"}},"required":[]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        urls = _resolve_urls(arguments)
        if not urls:
            raise ValueError("网页读取工具缺少 url 或 urls 参数")
        pages: list[dict] = []
        content_parts: list[str] = []
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True) as client:
            for url in urls:
                response = client.get(url, headers={"User-Agent": "PaiAgent-one/1.0"})
                text = response.text
                truncated = text[:MAX_PAGE_CHARS]
                pages.append({"url": url, "content": truncated})
                content_parts.append(f"URL: {url}\n{truncated}\n\n")
        return {
            "pages": pages,
            "content": "".join(content_parts).strip(),
            "citations": [page["url"] for page in pages],
        }


class LoadSkillDetailTool(AgentTool):
    name = "load_skill_detail"
    description = "加载指定 Skill 的完整指南内容。需要深入使用某个技能时调用。"
    input_schema = '{"type":"object","properties":{"skill_name":{"type":"string","description":"要加载的技能名称"}},"required":["skill_name"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        skill_name = arguments.get("skill_name")
        skill_name = str(skill_name) if skill_name is not None else ""
        if not skill_name.strip():
            return {"error": "缺少 skill_name"}
        skill = skill_registry.get_skill(skill_name)
        if skill is None:
            return {"error": f"未找到 Skill: {skill_name}"}
        return {"skillName": skill_name, "content": skill.full_content()}


class LoadSkillReferenceTool(AgentTool):
    name = "load_skill_reference"
    description = "加载指定 Skill 的参考文档内容。需要模板、示例或更细资料时调用。"
    input_schema = '{"type":"object","properties":{"skill_name":{"type":"string"},"reference_name":{"type":"string","description":"参考文档名称，不含 .md 后缀"}},"required":["skill_name","reference_name"]}'

    def execute(self, arguments: dict, context: ToolContext) -> dict:
        skill_name = str(arguments.get("skill_name") or "")
        reference_name = str(arguments.get("reference_name") or "")
        if not skill_name.strip():
            return {"error": "缺少 skill_name"}
        if not reference_name.strip():
            return {"error": "缺少 reference_name"}
        return {
            "skillName": skill_name,
            "referenceName": reference_name,
            "content": skill_registry.load_reference(skill_name, reference_name),
        }


_ALL_TOOLS: list[AgentTool] = [
    ReadCurrentInputTool(),
    KnowledgeRetrieveTool(),
    MemoryRetrieveTool(),
    MemoryWriteTool(),
    WebSearchTool(),
    WebFetchTool(),
    LoadSkillDetailTool(),
    LoadSkillReferenceTool(),
]

_TOOLS: dict[str, AgentTool] = {tool.name: tool for tool in _ALL_TOOLS}


def get_all_tools() -> list[AgentTool]:
    return list(_ALL_TOOLS)


def get_tools(selected_tool_names: Optional[list[str]]) -> list[AgentTool]:
    if not selected_tool_names:
        return get_all_tools()
    selected: list[AgentTool] = []
    for name in selected_tool_names:
        tool = _TOOLS.get(name)
        if tool is not None:
            selected.append(tool)
    return selected


def get_required_tool(name: str) -> AgentTool:
    tool = _TOOLS.get(name)
    if tool is None:
        raise ValueError(f"不支持的 Agent 工具: {name}")
    return tool
