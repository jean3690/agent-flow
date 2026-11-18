from __future__ import annotations

import httpx

from .errors import ApiError
from .resources.knowledge import KnowledgeResource
from .resources.mcp import McpResource
from .resources.skills import SkillResource
from .resources.workflows import WorkflowResource


class AgentFlowClient:
    """Client for the Agent Flow service.

    Authenticate with either an API Key (X-API-Key) for machine-to-machine calls
    or a JWT bearer token obtained from auth.login.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 120.0,
        transport: object | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        elif token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )

        self.workflows = WorkflowResource(self)
        self.knowledge = KnowledgeResource(self)
        self.skills = SkillResource(self)
        self.mcp = McpResource(self)

    def request(self, method: str, path: str, **kwargs) -> object:
        resp = self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text)
        data = resp.json()
        if data.get("code", 0) != 0:
            raise ApiError(data.get("code"), data.get("message", "error"), data)
        return data.get("data")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AgentFlowClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
