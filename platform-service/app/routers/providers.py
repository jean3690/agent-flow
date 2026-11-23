from __future__ import annotations

from fastapi import APIRouter, Request

from app.database import session_scope
from app.serialization import ok
from app.services.providers import ProviderService

router = APIRouter(prefix="/api/llm-providers", tags=["providers"])
service = ProviderService()


@router.get("")
def list_providers():
    with session_scope() as session:
        return ok(service.list(session))


@router.put("/{provider}")
def save_provider(provider: str, request: Request):
    payload = request.state.body or {}
    with session_scope() as session:
        service.save(session, provider, payload.get("apiKey"), payload.get("baseUrl"))
        return ok()


@router.delete("/{provider}")
def clear_provider(provider: str):
    with session_scope() as session:
        service.clear(session, provider)
        return ok()


@router.post("/{provider}/test")
def test_provider(provider: str, request: Request):
    payload = request.state.body or {}
    with session_scope() as session:
        return ok(
            service.test(session, provider, payload.get("apiKey"), payload.get("baseUrl"), payload.get("model"))
        )


@router.get("/{provider}/models")
def provider_models(provider: str):
    with session_scope() as session:
        return ok(service.models(session, provider))
