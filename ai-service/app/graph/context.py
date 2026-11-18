from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.core.events import EventBus
from app.mcp_client import McpServerConfig
from app.schemas.execution import ProviderConfig
from app.schemas.flow import Flow


@dataclass
class NodeContext:
    run_id: str
    settings: Settings
    flow: Flow
    bus: EventBus
    # 记忆节点需要归属信息；由 Java 在执行 payload 中下发
    workflow_id: str | None = None
    user_id: int | None = None
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    resume_cache: dict[str, dict] = field(default_factory=dict)
    # 子工作流 / foreach 循环体由 Java 在提交执行时内联到 payload.subflows
    subflows: dict[str, Flow] = field(default_factory=dict)
    depth: int = 0
    seq: int = 0
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
    executed: list[str] = field(default_factory=list)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def emit(self, event: str, **data) -> None:
        self.bus.emit(event, runId=self.run_id, **data)

    def credentials(self, provider: str | None) -> tuple[str, str]:
        """Resolve (api_key, base_url): request override first, then environment."""
        key = (provider or "openai").lower()
        override = self.providers.get(key)
        api_key = (override.api_key if override else "") or self.settings.api_key_for(key)
        base_url = (override.base_url if override else "") or self.settings.base_url_for(key)
        return api_key, base_url

    def mock_for(self, provider: str | None) -> bool:
        if provider == "mock":
            return True
        mode = (self.settings.mock_mode or "auto").lower()
        if mode == "always":
            return True
        if mode == "never":
            return False
        api_key, _ = self.credentials(provider or "openai")
        return not api_key
