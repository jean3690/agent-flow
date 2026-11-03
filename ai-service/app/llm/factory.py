from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator

from app.config import Settings
from app.core.errors import ModelNotConfiguredError
from app.llm.providers import provider_spec


def build_chat_model(
    settings: Settings,
    provider: str,
    model: str | None = None,
    *,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
):
    from langchain_openai import ChatOpenAI

    spec = provider_spec(provider)
    resolved_key = api_key if api_key is not None else settings.api_key_for(spec.key)
    if not resolved_key:
        raise ModelNotConfiguredError(f"provider {spec.key} 未配置 API Key", detail={"provider": spec.key})
    resolved_base = base_url if base_url is not None else settings.base_url_for(spec.key)
    kwargs = {
        "model": model or spec.default_model,
        "api_key": resolved_key,
        "base_url": resolved_base or None,
        "temperature": temperature,
        "streaming": True,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


def _mock_body(prompt: str, model: str) -> str:
    snippet = " ".join((prompt or "").split())[:160]
    return (
        f"[mock:{model}] 这是本地模拟输出，未调用真实模型。\n\n"
        f"收到内容：{snippet}\n\n"
        "要点：\n"
        "1. 当前处于 AI_MOCK_MODE，工作流编排、节点流转与 SSE 事件均真实执行。\n"
        "2. 配置对应厂商的 API Key 后即可切换为真实模型输出。\n"
        "3. 该段文本用于验证整条链路（前端 → Java → Python → SSE 回传）。"
    )


async def mock_stream(prompt: str, model: str, chunk_size: int = 8) -> AsyncIterator[str]:
    body = _mock_body(prompt, model)
    for index in range(0, len(body), chunk_size):
        yield body[index : index + chunk_size]
        await asyncio.sleep(0.012 + random.random() * 0.008)
