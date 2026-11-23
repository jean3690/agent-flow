from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

import httpx

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
    endpoint = chat_endpoint(normalized_provider, api_url)
    payload = {
        "model": normalized_model,
        "messages": messages,
        "temperature": 0.7 if temperature is None else temperature,
        "stream": on_chunk is not None,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    if on_chunk is not None:
        accumulated = ""
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    text = response.read().decode("utf-8", errors="ignore")
                    raise RuntimeError(f"LLM 调用失败, HTTP {response.status_code}: {text}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line or line == "[DONE]":
                        if line == "[DONE]":
                            break
                        continue
                    try:
                        chunk_payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk_payload.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    chunk = _content_to_text(delta.get("content"))
                    if chunk:
                        accumulated += chunk
                        on_chunk(chunk, accumulated)
        return {"content": accumulated, "inputTokens": 0, "outputTokens": 0, "totalTokens": 0}

    with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        response = client.post(endpoint, json=payload, headers=headers)

    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"LLM 调用失败, HTTP {response.status_code}: {response.text[:800]}")

    try:
        result = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM 返回内容无法解析: {response.text[:500]}") from exc

    choices = result.get("choices") or []
    content = ""
    if choices:
        message = choices[0].get("message") or {}
        content = _content_to_text(message.get("content"))
    input_tokens, output_tokens, total_tokens = _usage_from(result)
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
