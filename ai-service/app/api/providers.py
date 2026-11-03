from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings
from app.llm.factory import build_chat_model
from app.llm.providers import PROVIDERS, provider_catalog, provider_spec

router = APIRouter(prefix="/v1/providers", tags=["providers"])


class ProviderTestRequest(BaseModel):
    provider: str = "openai"
    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="", alias="baseUrl")
    model: str | None = None

    model_config = {"populate_by_name": True}


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

    api_key = request.api_key.strip() or settings.api_key_for(spec.key)
    base_url = request.base_url.strip() or settings.base_url_for(spec.key)
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
