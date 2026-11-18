import asyncio

import httpx
import pytest

from app.api import providers as api
from app.api.providers import ProviderModelsRequest


class _EmptySettings:
    def api_key_for(self, provider):
        return ""

    def base_url_for(self, provider):
        return ""


def test_models_endpoint_appends_v1_only_when_missing():
    assert api._models_endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/models"
    assert api._models_endpoint("https://proxy.example.com") == "https://proxy.example.com/v1/models"
    assert api._models_endpoint("https://open.bigmodel.cn/api/paas/v4") == "https://open.bigmodel.cn/api/paas/v4/models"


def test_fetch_model_ids_parses_ids_and_deduplicates():
    def handler(request):
        assert request.url.path.endswith("/models")
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(200, json={
            "data": [{"id": "gpt-4o"}, "gpt-4o-mini", {"name": "deepseek-flash"}, {}, "gpt-4o"],
        })

    ids = asyncio.run(api._fetch_model_ids("https://api.openai.com/v1", "sk-test", transport=httpx.MockTransport(handler)))
    assert ids == ["gpt-4o", "gpt-4o-mini", "deepseek-flash"]


def test_fetch_model_ids_rejects_non_list_payload():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"data": "oops"}))
    assert asyncio.run(api._fetch_model_ids("https://x/v1", "k", transport=transport)) == []


def test_fetch_model_ids_raises_on_http_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "nope"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(api._fetch_model_ids("https://x/v1", "k", transport=transport))


def test_no_key_falls_back_to_static(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _EmptySettings())
    data = asyncio.run(api.list_provider_models(ProviderModelsRequest(provider="openai")))["data"]
    assert data["ok"] is False
    assert data["source"] == "static"
    assert data["models"] == list(api.provider_spec("openai").models)


def test_mock_provider_never_calls_upstream(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _EmptySettings())

    async def boom(*args, **kwargs):
        raise AssertionError("mock provider must not call upstream")

    monkeypatch.setattr(api, "_fetch_model_ids", boom)
    data = asyncio.run(api.list_provider_models(ProviderModelsRequest(provider="mock")))["data"]
    assert data["models"] == ["agentflow-mock"]
    assert data["source"] == "static"


def test_unknown_provider_does_not_leak_other_catalog():
    data = asyncio.run(api.list_provider_models(ProviderModelsRequest(provider="nope")))["data"]
    assert data["ok"] is False
    assert data["models"] == []


def test_upstream_models_are_returned(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _EmptySettings())

    async def fake(base_url, key, *, transport=None):
        assert key == "sk-live"
        assert base_url == "https://proxy.example/v1"
        return ["deepseek-flash", "deepseek-v4-pro"]

    monkeypatch.setattr(api, "_fetch_model_ids", fake)
    data = asyncio.run(api.list_provider_models(ProviderModelsRequest(
        provider="deepseek", apiKey="sk-live", baseUrl="https://proxy.example/v1")))["data"]
    assert data["ok"] is True
    assert data["source"] == "upstream"
    assert data["models"] == ["deepseek-flash", "deepseek-v4-pro"]


def test_error_message_masks_api_key(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: _EmptySettings())

    async def fake(base_url, key, *, transport=None):
        raise RuntimeError("boom for sk-secret-key")

    monkeypatch.setattr(api, "_fetch_model_ids", fake)
    data = asyncio.run(api.list_provider_models(ProviderModelsRequest(
        provider="openai", apiKey="sk-secret-key", baseUrl="https://x/v1")))["data"]
    assert "sk-secret-key" not in data["message"]
    assert data["source"] == "static"
    assert data["models"] == list(api.provider_spec("openai").models)
