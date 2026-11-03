import asyncio

from app.api import providers as providers_api
from app.api.providers import ProviderTestRequest
from app.config import Settings
from app.core.events import EventBus
from app.graph.context import NodeContext
from app.llm.providers import provider_catalog
from app.schemas.execution import ExecutionRequest, ProviderConfig
from app.schemas.flow import Flow


def _context(overrides: dict[str, ProviderConfig]) -> NodeContext:
    return NodeContext(
        run_id="run-test",
        settings=Settings(mock_mode="auto", openai_api_key="env-key", openai_base_url="https://env.example/v1"),
        flow=Flow(nodes=[], edges=[]),
        bus=EventBus(),
        providers=overrides,
    )


def test_catalog_exposes_provider_metadata():
    catalog = provider_catalog()
    keys = {item["provider"] for item in catalog}
    assert {"openai", "deepseek", "qwen", "zhipu", "aiping", "mock"} <= keys
    assert all("apiKey" not in item for item in catalog)


def test_request_override_wins_over_environment():
    ctx = _context({"openai": ProviderConfig(apiKey="db-key", baseUrl="https://proxy.example/v1")})
    assert ctx.credentials("openai") == ("db-key", "https://proxy.example/v1")


def test_empty_override_falls_back_to_environment():
    ctx = _context({"openai": ProviderConfig()})
    assert ctx.credentials("openai") == ("env-key", "https://env.example/v1")


def test_mock_mode_uses_effective_key():
    ctx = _context({})
    assert ctx.mock_for("openai") is False
    ctx.providers["deepseek"] = ProviderConfig(apiKey="db-key")
    assert ctx.mock_for("deepseek") is False
    assert ctx.mock_for("qwen") is True


def test_execution_request_parses_camel_case_providers():
    request = ExecutionRequest.model_validate(
        {
            "flow": {"nodes": [], "edges": []},
            "providers": {"openai": {"apiKey": "k", "baseUrl": "https://x/v1"}},
        }
    )
    assert request.providers["openai"].api_key == "k"
    assert request.providers["openai"].base_url == "https://x/v1"


def test_provider_test_endpoint_handles_mock_and_unknown():
    assert asyncio.run(providers_api.test_connection(ProviderTestRequest(provider="mock")))["data"]["ok"] is True
    unknown = asyncio.run(providers_api.test_connection(ProviderTestRequest(provider="unknown")))["data"]
    assert unknown["ok"] is False
    assert "未知服务商" in unknown["message"]
