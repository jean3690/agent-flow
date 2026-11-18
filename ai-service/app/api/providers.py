from __future__ import annotations

import asyncio
import re
import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.search import tavily_search
from app.llm.factory import build_chat_model
from app.llm.providers import PROVIDERS, provider_catalog, provider_spec

router = APIRouter(prefix="/v1/providers", tags=["providers"])


class ProviderCredentialsRequest(BaseModel):
    provider: str = "openai"
    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="", alias="baseUrl")

    model_config = {"populate_by_name": True}


class ProviderTestRequest(ProviderCredentialsRequest):
    model: str | None = None


class ProviderModelsRequest(ProviderCredentialsRequest):
    pass


@router.get("")
async def list_providers():
    settings = get_settings()
    data = []
    for spec in provider_catalog():
        api_key = settings.api_key_for(spec["provider"])
        data.append(
            {
                **spec,
                "envConfigured": bool(api_key),
                "baseUrl": settings.base_url_for(spec["provider"]) or "",
            }
        )
    return {"data": data}


@router.post("/test")
async def test_connection(request: ProviderTestRequest):
    settings = get_settings()
    if request.provider.lower() not in PROVIDERS:
        return {"data": {"ok": False, "message": f"未知服务商: {request.provider}"}}
    spec = provider_spec(request.provider)
    if spec.key == "mock":
        return {"data": {"ok": True, "latencyMs": 0, "model": spec.default_model, "mock": True}}
    if not spec.supports_chat and not spec.supports_search:
        return {"data": {"ok": False, "message": f"{spec.label} 不支持对话连通性测试，保存 Key 后请在对应节点验证"}}

    api_key = request.api_key.strip() or settings.api_key_for(spec.key)
    base_url = request.base_url.strip() or settings.base_url_for(spec.key)
    if spec.supports_search:
        if not api_key:
            return {"data": {"ok": False, "message": "未提供 API Key"}}
        started = time.perf_counter()
        try:
            data = await tavily_search(api_key, base_url or None, "agentflow connectivity check", limit=1,
                                       include_answer=False, timeout=15)
            return {
                "data": {
                    "ok": True,
                    "latencyMs": int((time.perf_counter() - started) * 1000),
                    "model": spec.default_model,
                    "results": len(data.get("results") or []),
                }
            }
        except Exception as exc:  # noqa: BLE001 - report the vendor error to the caller
            message = str(exc).replace(api_key, "***")
            return {"data": {"ok": False, "message": message[:500], "model": spec.default_model}}
    if not api_key:
        return {"data": {"ok": False, "message": "未提供 API Key"}}

    model = request.model or spec.default_model
    started = time.perf_counter()
    try:
        llm = build_chat_model(
            settings,
            spec.key,
            model,
            temperature=0,
            max_tokens=16,
            api_key=api_key,
            base_url=base_url or None,
        )
        await asyncio.wait_for(llm.ainvoke("ping"), timeout=20)
        return {
            "data": {
                "ok": True,
                "latencyMs": int((time.perf_counter() - started) * 1000),
                "model": model,
            }
        }
    except Exception as exc:  # noqa: BLE001 - provider errors are reported to the caller
        message = str(exc).replace(api_key, "***") if api_key else str(exc)
        return {"data": {"ok": False, "message": message[:500], "model": model}}


def _models_endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    suffix = "/models" if re.search(r"/v\d+$", base) else "/v1/models"
    return base + suffix


async def _fetch_model_ids(base_url: str, api_key: str, *, transport=None) -> list[str]:
    """Request an OpenAI-compatible /models endpoint. transport is injectable for tests."""
    async with httpx.AsyncClient(
        timeout=10, follow_redirects=True, transport=transport
    ) as client:
        response = await client.get(
            _models_endpoint(base_url),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        payload = response.json()

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    found: list[str] = []
    for item in items:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
        else:
            continue
        if isinstance(model_id, str) and model_id.strip():
            found.append(model_id.strip())
    return list(dict.fromkeys(found))


def _models_payload(provider: str, models: list[str], ok: bool, source: str, message: str) -> dict:
    return {"ok": ok, "source": source, "provider": provider, "models": models, "message": message}


@router.post("/models")
async def list_provider_models(request: ProviderModelsRequest):
    """Return the live model ids for a provider, falling back to the static catalog."""
    settings = get_settings()
    provider = (request.provider or "openai").strip().lower()
    if provider not in PROVIDERS:
        return {"data": _models_payload(provider, [], False, "static", f"未知服务商: {provider}")}

    spec = provider_spec(provider)
    static = list(spec.models)
    if spec.key == "mock":
        return {"data": _models_payload(provider, static, True, "static", "本地演示服务商，无需调用上游")}

    api_key = (request.api_key or "").strip() or settings.api_key_for(spec.key)
    base_url = (request.base_url or "").strip() or settings.base_url_for(spec.key)
    if not api_key:
        return {"data": _models_payload(provider, static, False, "static", "未提供 API Key，已回退内置模型清单")}
    if not base_url:
        return {"data": _models_payload(provider, static, False, "static", "未配置 Base URL，已回退内置模型清单")}

    try:
        models = await _fetch_model_ids(base_url, api_key)
        if not models:
            return {"data": _models_payload(provider, static, False, "static", "上游未返回可用模型，已回退内置模型清单")}
        return {"data": _models_payload(provider, models, True, "upstream", "")}
    except Exception as exc:  # noqa: BLE001 - upstream failures must not break the editor
        message = str(exc).replace(api_key, "***") if api_key else str(exc)
        return {"data": _models_payload(provider, static, False, "static", f"拉取模型列表失败：{message[:400]}")}
