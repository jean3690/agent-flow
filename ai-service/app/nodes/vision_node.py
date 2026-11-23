from __future__ import annotations

from typing import Any

from app.core.errors import NodeExecutionError
from app.core.storage import is_local_file_reference, model_image_reference, scoped_relative_path
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.llm.factory import build_chat_model
from app.llm.providers import provider_spec
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class VisionNodeExecutor(NodeExecutor):
    type = "vision_analyze"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "openai").lower()
        spec = provider_spec(provider)
        model = config.get("model") or spec.default_model
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        raw_template = str(config.get("imageUrl") or "").strip()
        try:
            image_ref = render(raw_template, names, strict=True).strip() if raw_template else ""
        except Exception:  # noqa: BLE001 - 模板变量缺失时回退到上游输出
            image_ref = ""
        if not image_ref:
            for value in reversed(list((state.get("outputs") or {}).values())):
                if isinstance(value, dict) and value.get("imageUrl"):
                    image_ref = str(value["imageUrl"])
                    break
        if not image_ref:
            raise NodeExecutionError(node.id, "视觉理解节点缺少图片地址")
        prompt = render(config.get("prompt") or "描述这张图片", names, strict=True)
        local = is_local_file_reference(image_ref)
        if local:
            scoped_relative_path(ctx.storage, image_ref)

        if ctx.mock_for(provider):
            text = (
                f"[mock:{model}] 视觉理解模拟输出，未调用真实模型。\n\n"
                f"图片：{image_ref}\n提示词：{prompt}\n"
                "配置支持视觉的模型 Key 后即可返回真实分析。"
            )
            return {"text": text, "imageUrl": image_ref, "model": model, "mock": True}

        image_url = await self._to_model_url(node, image_ref, ctx)
        api_key, base_url = ctx.credentials(provider)
        try:
            from langchain_core.messages import HumanMessage

            llm = build_chat_model(
                ctx.settings, provider, model, temperature=0.2,
                api_key=api_key or None, base_url=base_url or None,
            )
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]
            )
            response = await llm.ainvoke([message])
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part) for part in content
                )
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"视觉理解失败: {exc}") from exc

        return {
            "text": content or "",
            "imageUrl": image_ref,
            "model": model,
            "usage": getattr(response, "usage_metadata", None) or {},
            "mock": False,
        }

    async def _to_model_url(self, node: FlowNode, image_ref: str, ctx: NodeContext) -> str:
        """云厂商访问不了本地 /files，把本地文件转成 data URL。"""
        if not is_local_file_reference(image_ref):
            return image_ref
        return model_image_reference(ctx.storage, image_ref)
