from __future__ import annotations

from typing import Any

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.llm.factory import build_chat_model, mock_stream
from app.llm.providers import provider_spec
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode
from app.skills.registry import get_skill_registry


@register
class LlmNodeExecutor(NodeExecutor):
    type = "llm"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "openai").lower()
        spec = provider_spec(provider)
        model = config.get("model") or spec.default_model
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})

        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)
        system_prompt = render(config.get("systemPrompt") or "", names)

        skill_ids = config.get("skillIds") or []
        if skill_ids:
            registry = get_skill_registry()
            for skill_id in skill_ids:
                detail = registry.detail(skill_id)
                system_prompt = f"{system_prompt}\n\n## 技能: {detail['title']}\n{detail['content']}".strip()
            ctx.emit("node_log", nodeId=node.id, level="info", message=f"已加载技能: {', '.join(skill_ids)}")

        temperature = float(config.get("temperature") if config.get("temperature") is not None else 0.7)
        max_tokens = config.get("maxTokens")
        api_key, base_url = ctx.credentials(provider)
        messages = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("human", prompt))

        try:
            if ctx.mock_for(provider):
                parts: list[str] = []
                async for delta in mock_stream(prompt, model):
                    parts.append(delta)
                    ctx.emit("node_token", nodeId=node.id, delta=delta)
                text = "".join(parts)
                return {
                    "text": text,
                    "provider": provider,
                    "model": model,
                    "usage": {"promptTokens": len(prompt) // 4, "completionTokens": len(text) // 4},
                    "mock": True,
                }

            llm = build_chat_model(
                ctx.settings,
                provider,
                model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key or None,
                base_url=base_url or None,
            )
            parts = []
            usage = None
            from langchain_core.messages import HumanMessage, SystemMessage

            lc_messages = []
            if system_prompt:
                lc_messages.append(SystemMessage(content=system_prompt))
            lc_messages.append(HumanMessage(content=prompt))

            async for chunk in llm.astream(lc_messages):
                delta = chunk.content
                if isinstance(delta, list):
                    delta = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in delta)
                if delta:
                    parts.append(delta)
                    ctx.emit("node_token", nodeId=node.id, delta=delta)
                if getattr(chunk, "usage_metadata", None):
                    usage = chunk.usage_metadata
            text = "".join(parts)
            return {
                "text": text,
                "provider": provider,
                "model": model,
                "usage": usage or {},
                "mock": False,
            }
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"模型调用失败: {exc}") from exc
