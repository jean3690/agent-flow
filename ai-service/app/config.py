from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

# qwen 的环境变量名是 dashscope_*，与 provider key 不一致
_SETTINGS_ALIAS = {"qwen": "dashscope"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AI_", env_file=".env", extra="ignore")
    # Runtime-only storage context, never bindable through environment variables.
    _storage_owner_id: int | None = PrivateAttr(default=None)
    _storage_legacy: bool = PrivateAttr(default=False)

    service_port: int = 8000
    mock_mode: str = "auto"  # auto | always | never
    cors_origins: str = "*"
    output_dir: str = "./data/audio"
    # 用户上传 / 文件节点读写目录；留空时复用 output_dir，避免破坏历史媒体文件
    file_dir: str = ""
    max_upload_mb: int = 50
    max_read_chars: int = 200_000
    max_concurrency: int = Field(default=8, ge=1, le=256)
    event_buffer_max_events: int = Field(default=256, ge=1, le=100_000)
    event_buffer_max_bytes: int = Field(default=4_194_304, ge=256)
    event_max_bytes: int = Field(default=1_048_576, ge=256)
    event_heartbeat_seconds: float = Field(default=15, ge=1, le=300)
    platform_service_base_url: str = "http://127.0.0.1:8084"
    internal_token: str = "agent-flow-internal"
    managed_skills_dir: str = "./data/skills"
    # Explicit deployment-only exceptions for private MCP hosts (no wildcards).
    mcp_private_hosts: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Workspace host (without protocol/path), required by LiveTranslate 3.8.
    dashscope_api_host: str = ""
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    aiping_api_key: str = ""
    aiping_base_url: str = "https://aiping.cn/api/v1"
    step_api_key: str = ""
    step_base_url: str = "https://api.stepfun.com/v1"
    # APIFree 的入口因账号而异，默认留空，由「模型配置」页填写
    apifree_api_key: str = ""
    apifree_base_url: str = ""
    volcengine_api_key: str = ""
    volcengine_base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    agnes_api_key: str = ""
    agnes_base_url: str = "https://apihub.agnes-ai.com"
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com"

    @property
    def skills_dir(self) -> Path:
        return Path(os.getenv("AI_SKILLS_DIR", Path(__file__).parent / "skills" / "builtin"))

    @property
    def audio_dir(self) -> Path:
        path = Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def files_dir(self) -> Path:
        path = Path(self.file_dir) if self.file_dir.strip() else Path(self.output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def credentials_for(self, provider: str) -> tuple[str, str]:
        name = (provider or "").lower()
        field = _SETTINGS_ALIAS.get(name, name)
        key = (
            getattr(self, f"{field}_api_key", "")
            or os.getenv(f"{field.upper()}_API_KEY", "")
            or os.getenv(f"{name.upper()}_API_KEY", "")
        )
        return key, getattr(self, f"{field}_base_url", "")

    def api_key_for(self, provider: str) -> str:
        return self.credentials_for(provider)[0]

    def base_url_for(self, provider: str) -> str:
        return self.credentials_for(provider)[1]


@lru_cache
def get_settings() -> Settings:
    return Settings()
