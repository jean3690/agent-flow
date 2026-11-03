from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")

    service_port: int = 8000
    mock_mode: str = "auto"  # auto | always | never
    cors_origins: str = "*"
    output_dir: str = "./data/audio"
    max_concurrency: int = 8
    java_service_base_url: str = "http://127.0.0.1:8084"
    internal_token: str = "agent-flow-internal"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    aiping_api_key: str = ""
    aiping_base_url: str = "https://aiping.cn/api/v1"

    @property
    def skills_dir(self) -> Path:
        return Path(os.getenv("AI_SKILLS_DIR", Path(__file__).parent / "skills" / "builtin"))

    @property
    def audio_dir(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def api_key_for(self, provider: str) -> str:
        env = f"{provider.upper()}_API_KEY"
        return getattr(self, f"{provider}_api_key", "") or os.getenv(env, "")

    def base_url_for(self, provider: str) -> str:
        return getattr(self, f"{provider}_base_url", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
