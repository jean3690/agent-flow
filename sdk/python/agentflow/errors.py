from __future__ import annotations

from typing import Any, Optional


class AgentFlowError(Exception):
    """Base error for the Agent Flow SDK."""


class ApiError(AgentFlowError):
    """Raised when the Agent Flow API returns a non-zero code or HTTP error."""

    def __init__(self, code: Any, message: str, raw: Optional[Any] = None) -> None:
        self.code = code
        self.message = message
        self.raw = raw
        super().__init__(f"[{code}] {message}")
