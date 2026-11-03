from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.core.events import EventBus
from app.schemas.execution import ProviderConfig
from app.schemas.flow import Flow


@dataclass
class NodeContext:
    run_id: str
    settings: Settings
    flow: Flow
    bus: EventBus
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    resume_cache: dict[str, dict] = field(default_factory=dict)
    seq: int = 0
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
