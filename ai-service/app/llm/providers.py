from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    default_model: str
    models: tuple[str, ...]
    base_url_env: str
    supports_tts: bool = False


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        key="openai",
        label="OpenAI",
        default_model="gpt-4o-mini",
        models=("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
        base_url_env="OPENAI_BASE_URL",
        supports_tts=True,
    ),
    "deepseek": ProviderSpec(
        key="deepseek",
        label="DeepSeek",
        default_model="deepseek-chat",
        models=("deepseek-chat", "deepseek-reasoner"),
        base_url_env="DEEPSEEK_BASE_URL",
    ),
    "qwen": ProviderSpec(
        key="qwen",
        label="通义千问",
        default_model="qwen-plus",
        models=("qwen-plus", "qwen-max", "qwen-turbo"),
        base_url_env="DASHSCOPE_BASE_URL",
    ),
    "zhipu": ProviderSpec(
        key="zhipu",
        label="智谱 GLM",
        default_model="glm-4-flash",
        models=("glm-4-flash", "glm-4-plus", "glm-4-air"),
        base_url_env="ZHIPU_BASE_URL",
    ),
    "aiping": ProviderSpec(
        key="aiping",
        label="AiPing",
        default_model="gpt-4o-mini",
        models=("gpt-4o-mini", "claude-3-5-sonnet"),
        base_url_env="AIPING_BASE_URL",
    ),
    "mock": ProviderSpec(
        key="mock",
        label="Mock（本地演示）",
        default_model="agentflow-mock",
        models=("agentflow-mock",),
        base_url_env="",
    ),
}


def provider_spec(provider: str | None) -> ProviderSpec:
    key = (provider or "openai").lower()
    return PROVIDERS.get(key, PROVIDERS["openai"])


def list_models(has_key) -> list[dict]:
    result = []
    for spec in PROVIDERS.values():
        key = bool(has_key(spec.key)) or spec.key == "mock"
        for model in spec.models:
            result.append(
                {
                    "provider": spec.key,
                    "providerLabel": spec.label,
                    "model": model,
                    "configured": key,
                    "supportsTts": spec.supports_tts,
                }
            )
    return result


def provider_catalog() -> list[dict]:
    """Static provider metadata; credentials are resolved per request."""
    return [
        {
            "provider": spec.key,
            "label": spec.label,
            "defaultModel": spec.default_model,
            "models": list(spec.models),
            "supportsTts": spec.supports_tts,
        }
        for spec in PROVIDERS.values()
    ]
