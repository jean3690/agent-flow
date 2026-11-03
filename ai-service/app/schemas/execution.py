from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.flow import Flow


class ExecutionOptions(BaseModel):
    mock: bool | None = None
    timeout_ms: int = Field(default=120_000, alias="timeoutMs")
    debug: bool = False

    model_config = {"populate_by_name": True}


class ProviderConfig(BaseModel):
    """Per-run provider override; absent fields fall back to environment config."""

    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="", alias="baseUrl")

    model_config = {"populate_by_name": True}


class ExecutionRequest(BaseModel):
    run_id: str | None = Field(default=None, alias="runId")
    workflow_id: str | None = Field(default=None, alias="workflowId")
    flow: Flow
    input: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    # 断点续跑：nodeId -> 上次成功节点的输出对象；命中即跳过执行
    resume: dict[str, dict[str, Any]] = Field(default_factory=dict)
    options: ExecutionOptions = Field(default_factory=ExecutionOptions)

    model_config = {"populate_by_name": True}
