from __future__ import annotations

import json
from typing import Any

from app.agent_tools import TOOL_LABELS, TOOL_SPECS, execute_tool
from app.core.errors import NodeExecutionError
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.llm.factory import build_chat_model
from app.llm.providers import provider_spec
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode

DEFAULT_TOOLS = ["read_input"]


@register
class ReactAgentNodeExecutor(NodeExecutor):
    """Minimal tool-calling agent loop (OpenAI-compatible function calling)."""

    type = "react_agent"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "openai").lower()
        spec = provider_spec(provider)
        model = config.get("model") or spec.default_model
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})

        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)
        system_prompt = render(config.get("systemPrompt") or "", names)
        enabled = set(config.get("toolIds") or DEFAULT_TOOLS)
        max_steps = max(1, min(int(config.get("maxSteps") or 4), 8))
        schemas = [spec_item for spec_item in TOOL_SPECS if spec_item["function"]["name"] in enabled]

        if ctx.mock_for(provider):
            return await self._mock(node, ctx, config, prompt, model, enabled)

        api_key, base_url = ctx.credentials(provider)
        try:
            llm = build_chat_model(
                ctx.settings, provider, model, temperature=0.2,
                api_key=api_key or None, base_url=base_url or None,
            )
            from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

            messages: list[Any] = []
            if system_prompt:
                messages.append(SystemMessage(content=system_prompt))
            messages.append(HumanMessage(content=prompt))

            steps: list[dict[str, Any]] = []
            tools_used = 0
            chat = llm.bind_tools(schemas) if schemas else llm
            response = await chat.ainvoke(messages)

            for _ in range(max_steps):
                messages.append(response)
                calls = getattr(response, "tool_calls", None) or []
                if not calls:
                    return self._result(node, provider, model, response, steps, tools_used, False)

                for call in calls:
                    name = call.get("name") or ""
                    args = call.get("args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}
                    label = TOOL_LABELS.get(name, name)
                    ctx.emit("node_log", nodeId=node.id, level="info", message=f"调用工具 {label}: {args}")
                    try:
                        result = await execute_tool(name, args, state, ctx, config)
                    except Exception as exc:  # noqa: BLE001 - keep the loop alive
                        result = f"错误：工具执行失败 {exc}"
                    tools_used += 1
                    steps.append({"tool": name, "args": args, "result": result[:500]})
                    ctx.emit(
                        "node_log", nodeId=node.id, level="info",
                        message=f"工具 {label} 返回 {len(result)} 字符",
                    )
                    messages.append(ToolMessage(content=result[:8000], tool_call_id=call.get("id") or name))

                response = await chat.ainvoke(messages)

            ctx.emit("node_log", nodeId=node.id, level="warn",
                     message=f"达到最大推理步数 {max_steps}，直接生成最终回答")
            messages.append(HumanMessage(content="请基于以上工具结果直接给出最终答案，不要再调用工具。"))
            final = await (llm.ainvoke(messages))
            return self._result(node, provider, model, final, steps, tools_used, False, True)
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"Agent 调用失败: {exc}") from exc

    async def _mock(self, node: FlowNode, ctx: NodeContext, config: dict[str, Any],
                    prompt: str, model: str, enabled: set[str]) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        knowledge = ""
        if "knowledge_search" in enabled and str(config.get("knowledgeBaseId") or "").strip():
            ctx.emit("node_log", nodeId=node.id, level="info", message="调用工具 知识检索")
            knowledge = await execute_tool("knowledge_search", {"query": prompt}, {}, ctx, config)
            steps.append({"tool": "knowledge_search", "args": {"query": prompt}, "result": knowledge[:500]})
        text = (
            f"[mock:{model}] ReAct Agent 本地模拟输出，未调用真实模型。\n\n"
            f"任务：{prompt}\n"
            f"可用工具：{', '.join(sorted(enabled))}\n"
        )
        if knowledge:
            text += f"\n工具返回：\n{knowledge}"
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"模拟完成，工具调用 {len(steps)} 次")
        return {
            "text": text,
            "steps": steps,
            "toolCalls": len(steps),
            "provider": "mock",
            "model": model,
            "mock": True,
        }

    def _result(self, node: FlowNode, provider: str, model: str, response: Any,
                steps: list[dict[str, Any]], tools_used: int, mock: bool, exceeded: bool = False) -> dict[str, Any]:
        content = getattr(response, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return {
            "text": content or "",
            "steps": steps,
            "toolCalls": tools_used,
            "provider": provider,
            "model": model,
            "usage": getattr(response, "usage_metadata", None) or {},
            "mock": mock,
            "exceededSteps": exceeded,
        }
