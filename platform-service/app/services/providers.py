from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_client import AiClient, get_ai
from app.errors import BizError
from app.models import LlmProviderConfig
from app.security import CryptoService, mask_secret

PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")


class ProviderService:
    def __init__(self, crypto: CryptoService | None = None, ai: AiClient | None = None) -> None:
        self.crypto = crypto or CryptoService()
        self.ai = ai or get_ai()

    def list(self, session: Session) -> list[dict[str, Any]]:
        stored = {item.provider: item for item in session.scalars(select(LlmProviderConfig)).all()}
        result: list[dict[str, Any]] = []
        for item in self.ai.data("/v1/providers") or []:
            provider = str(item.get("provider") or "")
            config = stored.get(provider)
            db_key = config is not None and bool((config.api_key or "").strip())
            env_key = bool(item.get("envConfigured"))
            is_mock = provider == "mock"
            base_url = (
                config.base_url
                if config is not None and (config.base_url or "").strip()
                else str(item.get("baseUrl") or "")
            )
            result.append(
                {
                    "provider": provider,
                    "label": str(item.get("label") or provider),
                    "defaultModel": str(item.get("defaultModel") or ""),
                    "models": [str(value) for value in (item.get("models") or [])],
                    "supportsTts": bool(item.get("supportsTts")),
                    "configured": db_key or env_key or is_mock,
                    "source": "DB" if db_key else ("ENV" if env_key else "NONE"),
                    "baseUrl": base_url,
                    "apiKeyMasked": mask_secret(self.crypto.decrypt(config.api_key)) if db_key and config else "",
                }
            )
        return result

    def save(self, session: Session, provider: str, api_key: str | None, base_url: str | None) -> None:
        self._require(provider)
        api_key = (api_key or "").strip()
        base_url = (base_url or "").strip()
        existing = self._find(session, provider)
        if existing is None:
            if not api_key:
                raise BizError("请填写 API Key")
            session.add(
                LlmProviderConfig(
                    provider=provider,
                    api_key=self.crypto.encrypt(api_key),
                    base_url=base_url,
                    enabled=1,
                )
            )
            return
        if api_key:
            existing.api_key = self.crypto.encrypt(api_key)
        if not (existing.api_key or "").strip():
            raise BizError("请填写 API Key")
        existing.base_url = base_url
        existing.enabled = 1

    def clear(self, session: Session, provider: str) -> None:
        self._require(provider)
        existing = self._find(session, provider)
        if existing is not None:
            session.delete(existing)

    def test(self, session: Session, provider: str, api_key: str | None, base_url: str | None,
             model: str | None) -> Any:
        self._require(provider)
        stored = self._find(session, provider)
        payload: dict[str, Any] = {
            "provider": provider,
            "apiKey": (api_key or "").strip()
            if api_key and api_key.strip()
            else (self.crypto.decrypt(stored.api_key) if stored else ""),
            "baseUrl": (base_url or "").strip()
            if base_url and base_url.strip()
            else (stored.base_url if stored else ""),
        }
        if model and model.strip():
            payload["model"] = model.strip()
        return (self.ai.post_json("/v1/providers/test", payload) or {}).get("data")

    def models(self, session: Session, provider: str) -> Any:
        self._require(provider)
        credentials = self.credentials(session, provider) or {}
        return (
            self.ai.post_json(
                "/v1/providers/models",
                {
                    "provider": provider,
                    "apiKey": credentials.get("apiKey", ""),
                    "baseUrl": credentials.get("baseUrl", ""),
                },
            )
            or {}
        ).get("data")

    def credentials(self, session: Session, provider: str) -> dict[str, str] | None:
        config = self._find(session, provider)
        if config is None or not (config.api_key or "").strip():
            return None
        return {
            "apiKey": self.crypto.decrypt(config.api_key) or "",
            "baseUrl": config.base_url if (config.base_url or "").strip() else "",
        }

    def credentials_for_run(self, session: Session) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        rows = session.scalars(select(LlmProviderConfig).where(LlmProviderConfig.enabled == 1)).all()
        for item in rows:
            if not (item.api_key or "").strip():
                continue
            entry = {"apiKey": self.crypto.decrypt(item.api_key) or ""}
            if (item.base_url or "").strip():
                entry["baseUrl"] = item.base_url or ""
            result[item.provider] = entry
        return result

    def _find(self, session: Session, provider: str) -> LlmProviderConfig | None:
        return session.scalar(select(LlmProviderConfig).where(LlmProviderConfig.provider == provider))

    @staticmethod
    def _require(provider: str) -> None:
        if not provider or not PROVIDER_PATTERN.match(provider):
            raise BizError(f"非法服务商标识: {provider}")
