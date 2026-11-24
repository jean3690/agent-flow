from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from openai import OpenAI, OpenAIError

logger = logging.getLogger("agentflow.llm")

CHAT_COMPLETIONS_SUFFIX = "/v1/chat/completions"
V1_SUFFIX = "/v1"
AGENT_PLAN_CHAT_PATH = "/api/plan/v3/chat/completions"
TEMPLATE_RE = re.compile(r"\{\{(.*?)\}\}")


def normalize_provider(provider: Optional[str]) -> str:
    if not provider:
        return ""
    normalized = provider.strip().lower()
    mapping = {
        "open ai": "openai",
        "deep seek": "deepseek",
        "通义千问": "qwen",
        "dashscope": "qwen",
        "aliyun": "qwen",
        "stepfun": "step",
        "阶跃星辰": "step",
        "智谱": "zhipu",
        "ai ping": "ai_ping",
        "agnes ai": "agnes",
        "api free": "apifree",
        "apifree.ai": "apifree",
        "skyclaw": "apifree",
        "skyclaw-v1": "apifree",
        "skyclaw-v1.0": "apifree",
        "skyclaw-v1-lite": "apifree",
        "skyclaw-v1.0-lite": "apifree",
        "skywork-ai/skyclaw-v1": "apifree",
        "skywork-ai/skyclaw-v1-lite": "apifree",
        "volcengine": "volcengine_agent_plan",
        "ark": "volcengine_agent_plan",
        "agent_plan": "volcengine_agent_plan",
        "agent plan": "volcengine_agent_plan",
        "火山方舟": "volcengine_agent_plan",
    }
    return mapping.get(normalized, normalized)


def normalize_model(provider: str, model: Optional[str]) -> str:
    if not model:
        return ""
    if provider != "apifree":
        return model
    normalized = model.strip().lower()
    mapping = {
        "skyclaw": "skywork-ai/skyclaw-v1",
        "skyclaw-v1": "skywork-ai/skyclaw-v1",
        "skyclaw-v1.0": "skywork-ai/skyclaw-v1",
        "skyclaw-lite": "skywork-ai/skyclaw-v1-lite",
        "skyclaw-v1-lite": "skywork-ai/skyclaw-v1-lite",
        "skyclaw-v1.0-lite": "skywork-ai/skyclaw-v1-lite",
    }
    return mapping.get(normalized, model.strip())


def _strip_suffix_ignore_case(value: str, suffix: str) -> str:
    if value.lower().endswith(suffix.lower()):
        return value[: -len(suffix)]
    return value


def strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def normalize_base_url(api_url: Optional[str]) -> str:
    normalized = strip_trailing_slash((api_url or "").strip())
    normalized = _strip_suffix_ignore_case(normalized, CHAT_COMPLETIONS_SUFFIX)
    normalized = _strip_suffix_ignore_case(normalized, V1_SUFFIX)
    return strip_trailing_slash(normalized)


def normalize_agent_plan_base_url(api_url: Optional[str]) -> str:
    normalized = strip_trailing_slash((api_url or "").strip())
    normalized = _strip_suffix_ignore_case(normalized, AGENT_PLAN_CHAT_PATH)
    normalized = _strip_suffix_ignore_case(normalized, "/api/plan/v3")
    return strip_trailing_slash(normalized)


def chat_endpoint(provider: str, api_url: Optional[str]) -> str:
    if provider == "volcengine_agent_plan":
        return normalize_agent_plan_base_url(api_url) + AGENT_PLAN_CHAT_PATH
    return normalize_base_url(api_url) + CHAT_COMPLETIONS_SUFFIX


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _usage_from(payload: dict) -> tuple[int, int, int]:
    usage = payload.get("usage") or {}
    if not isinstance(usage, dict):
        return 0, 0, 0
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    total_tokens = usage.get("total_tokens")
    try:
        input_value = int(input_tokens or 0)
    except (TypeError, ValueError):
        input_value = 0
    try:
        output_value = int(output_tokens or 0)
    except (TypeError, ValueError):
        output_value = 0
    try:
        total_value = int(total_tokens) if total_tokens is not None else input_value + output_value
    except (TypeError, ValueError):
        total_value = input_value + output_value
    return input_value, output_value, total_value


def _client_base_url(provider: str, api_url: Optional[str]) -> str:
    if provider == "volcengine_agent_plan":
        return normalize_agent_plan_base_url(api_url) + "/api/plan/v3"
    return normalize_base_url(api_url) + "/v1"


def chat_completion(
    provider: str,
    api_url: str,
    api_key: str,
    model: str,
    temperature: Optional[float],
    messages: list[dict],
    on_chunk: Optional[Callable[[str, str], None]] = None,
) -> dict:
    normalized_provider = normalize_provider(provider)
    normalized_model = normalize_model(normalized_provider, model)
    client = OpenAI(
        api_key=api_key or "EMPTY",
        base_url=_client_base_url(normalized_provider, api_url),
        timeout=120.0,
        max_retries=1,
    )
    temperature_value = 0.7 if temperature is None else temperature

    if on_chunk is not None:
        accumulated = ""
        try:
            stream = client.chat.completions.create(
                model=normalized_model,
                messages=messages,
                temperature=temperature_value,
                stream=True,
            )
            for chunk in stream:
                choices = chunk.choices or []
                if not choices:
                    continue
                delta_text = _content_to_text(getattr(choices[0].delta, "content", None))
                if delta_text:
                    accumulated += delta_text
                    on_chunk(delta_text, accumulated)
        except OpenAIError as exc:
            raise RuntimeError(f"LLM 调用失败: {exc}") from exc
        return {"content": accumulated, "inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

    try:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=temperature_value,
            stream=False,
        )
    except OpenAIError as exc:
        raise RuntimeError(f"LLM 调用失败: {exc}") from exc

    content = _content_to_text(response.choices[0].message.content) if response.choices else ""
    usage = response.usage
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (input_tokens + output_tokens))
    return {
        "content": content,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
    }


class PromptTemplateService:
    def process_template(
        self,
        prompt_template: Optional[str],
        input_params: Optional[list[dict]],
        runtime_input: dict,
    ) -> str:
        if prompt_template is None:
            return ""
        values: dict[str, str] = {}
        for param in input_params or []:
            name = param.get("name")
            param_type = param.get("type")
            if param_type == "input":
                value = param.get("value")
                if value is not None:
                    values[str(name)] = str(value)
            elif param_type == "reference":
                reference = param.get("referenceNode")
                if reference and "." in str(reference):
                    ref_key = str(reference).split(".")[-1]
                    ref_value = runtime_input.get(ref_key)
                    if ref_value is None and ref_key == "user_input":
                        ref_value = runtime_input.get("input")
                    if ref_value is not None:
                        values[str(name)] = str(ref_value)
        result = prompt_template
        for match in TEMPLATE_RE.finditer(prompt_template):
            name = match.group(1).strip()
            result = result.replace("{{" + name + "}}", values.get(name, ""))
        return result


prompt_template_service = PromptTemplateService()