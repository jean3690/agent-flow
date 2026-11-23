from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PRICING = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-chat": {"input": 0.00027, "output": 0.0011},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
    "glm-4": {"input": 0.00014, "output": 0.00014},
    "agentflow-mock": {"input": 0, "output": 0},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    server_port: int = Field(default=8084, alias="SERVER_PORT")
    database_url: str = Field(default="sqlite:///./data/agentflow.db", alias="DATABASE_URL")

    jwt_secret: str = Field(default="agent-flow-local-secret-key-please-change", alias="JWT_SECRET")
    jwt_expire_hours: int = Field(default=12, alias="JWT_EXPIRE_HOURS")
    default_username: str = Field(default="admin", alias="APP_AUTH_DEFAULT_USERNAME")
    default_password: str = Field(default="admin123", alias="APP_AUTH_DEFAULT_PASSWORD")

    ai_service_base_url: str = Field(default="http://127.0.0.1:8000", alias="AI_SERVICE_BASE_URL")
    ai_service_timeout_ms: int = Field(default=120_000, alias="AI_SERVICE_TIMEOUT_MS")
    ai_connect_timeout_ms: int = Field(default=5_000, alias="AI_SERVICE_CONNECT_TIMEOUT_MS")
    internal_token: str = Field(default="agent-flow-internal", alias="AI_INTERNAL_TOKEN")
    crypto_key: str = Field(default="agent-flow-local-crypto-key", alias="CRYPTO_KEY")

    cors_allowed_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="CORS_ALLOWED_ORIGINS"
    )

    execution_core_pool_size: int = Field(default=4, alias="EXECUTION_CORE_POOL_SIZE", ge=1)
    execution_max_pool_size: int = Field(default=32, alias="EXECUTION_MAX_POOL_SIZE", ge=1)
    execution_queue_capacity: int = Field(default=200, alias="EXECUTION_QUEUE_CAPACITY", ge=0)
    execution_transport_grace_ms: int = Field(default=5_000, alias="EXECUTION_TRANSPORT_GRACE_MS", ge=0)
    execution_max_event_chars: int = Field(default=2_000_000, alias="EXECUTION_MAX_EVENT_CHARS", ge=256)

    pricing_json: str = Field(default="", alias="MODEL_PRICING_JSON")

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]

    @property
    def pricing(self) -> dict[str, dict[str, float]]:
        if not self.pricing_json.strip():
            return DEFAULT_PRICING
        try:
            parsed = json.loads(self.pricing_json)
            return {
                str(name): {
                    "input": float(body.get("input", 0)),
                    "output": float(body.get("output", 0)),
                }
                for name, body in parsed.items()
                if isinstance(body, dict)
            }
        except (ValueError, AttributeError):
            return DEFAULT_PRICING

    @property
    def resources_dir(self) -> Path:
        return Path(__file__).parent / "resources"


@lru_cache
def get_settings() -> Settings:
    return Settings()
