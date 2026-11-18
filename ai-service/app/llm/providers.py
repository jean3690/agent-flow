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
    # 非对话类服务商（图像 / 视频 / 联网搜索）不进大模型节点下拉
    supports_chat: bool = True
    supports_search: bool = False


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
    "step": ProviderSpec(
        key="step",
        label="阶跃星辰 StepFun",
        default_model="step-2-16k",
        models=("step-2-16k", "step-1-32k", "step-1v-8k"),
        base_url_env="STEP_BASE_URL",
    ),
    "apifree": ProviderSpec(
        key="apifree",
        label="APIFree / SkyClaw",
        default_model="skywork-ai/skyclaw-v1",
        models=("skywork-ai/skyclaw-v1", "skywork-ai/skyclaw-v1-lite", "gpt-4o-mini"),
        base_url_env="APIFREE_BASE_URL",
    ),
    "volcengine": ProviderSpec(
        key="volcengine",
        label="火山方舟 Agent Plan",
        default_model="doubao-seed-1-6-250615",
        models=("doubao-seed-1-6-250615", "doubao-1-5-pro-32k-250115"),
        base_url_env="VOLCENGINE_BASE_URL",
    ),
    "agnes": ProviderSpec(
        key="agnes",
        label="Agnes AI（视频）",
        default_model="agnes-video-v2.0",
        models=(),
        base_url_env="AGNES_BASE_URL",
        supports_chat=False,
    ),
    "tavily": ProviderSpec(
        key="tavily",
        label="Tavily 联网搜索",
        default_model="tavily-search",
        models=(),
        base_url_env="TAVILY_BASE_URL",
        supports_chat=False,
        supports_search=True,
    ),
    "mock": ProviderSpec(
        key="mock",
        label="Mock（本地演示）",
        default_model="agentflow-mock",
        models=("agentflow-mock",),
        base_url_env="",
    ),
}

# 兼容 PaiAgent 里的服务商写法，统一收敛到本项目的 provider key
_ALIASES = {
    "stepfun": "step",
    "阶跃星辰": "step",
    "ai_ping": "aiping",
    "ai ping": "aiping",
    "apifree.ai": "apifree",
    "skyclaw": "apifree",
    "skyclaw-v1": "apifree",
    "skyclaw-v1-lite": "apifree",
    "ark": "volcengine",
    "volcengine_agent_plan": "volcengine",
    "agent_plan": "volcengine",
    "agent plan": "volcengine",
}


def provider_spec(provider: str | None) -> ProviderSpec:
    key = (provider or "openai").strip().lower()
    key = _ALIASES.get(key, key)
    return PROVIDERS.get(key, PROVIDERS["openai"])


def chat_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.supports_chat]


def search_providers() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS.values() if spec.supports_search]


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
            "supportsChat": spec.supports_chat,
            "supportsSearch": spec.supports_search,
        }
        for spec in PROVIDERS.values()
    ]
