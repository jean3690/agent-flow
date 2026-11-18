from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

if TYPE_CHECKING:
    from ..client import AgentFlowClient


def _server_path(server_id: int) -> str:
    if isinstance(server_id, bool) or not isinstance(server_id, int) or server_id <= 0:
        raise ValueError("server_id must be a positive integer")
    return f"/api/mcp-servers/{server_id}"


class McpResource:
    """Manage platform MCP configurations, not direct MCP transport connections."""

    def __init__(self, client: AgentFlowClient) -> None:
        self._c = client

    def list(self) -> Any:
        return self._c.request("GET", "/api/mcp-servers")

    def create(
        self, name: str, url: str, *, headers: Optional[Mapping[str, str]] = None,
        timeout_ms: int = 15000, enabled: bool = True,
    ) -> Any:
        """New configurations have no authorized tools; discover before granting."""
        payload: dict[str, Any] = {
            "name": name, "url": url, "allowedTools": [],
            "timeoutMs": timeout_ms, "enabled": enabled,
        }
        if headers is not None:
            payload["headers"] = dict(headers)
        return self._c.request("POST", "/api/mcp-servers", json=payload)

    def update(
        self, server_id: int, *, name: str, url: str, allowed_tools: Sequence[str],
        timeout_ms: int, enabled: bool, headers: Optional[Mapping[str, str]] = None,
        clear_headers: bool = False,
    ) -> Any:
        """Full update: omit headers to retain credentials; clear explicitly.

        Changing the URL clears old credentials and discovered tools on the server.
        Required fields avoid silently enabling a service or revoking its tools.
        """
        path = _server_path(server_id)
        if isinstance(allowed_tools, (str, bytes)):
            raise TypeError("allowed_tools must be a sequence of tool names, not a string")
        tools = list(allowed_tools)
        if any(not isinstance(tool, str) or not tool or len(tool) > 128 for tool in tools):
            raise ValueError("allowed_tools contains an invalid tool name")
        payload: dict[str, Any] = {
            "name": name, "url": url, "allowedTools": tools,
            "timeoutMs": timeout_ms, "enabled": enabled, "clearHeaders": clear_headers,
        }
        if headers is not None:
            payload["headers"] = dict(headers)
        return self._c.request("PUT", path, json=payload)

    def discover(self, server_id: int) -> Any:
        """Test the saved connection; inspect result['ok'] before authorizing."""
        return self._c.request("POST", _server_path(server_id) + "/discover")

    def tools(self, server_id: int) -> Any:
        """Return approved tools, not every discovered tool."""
        return self._c.request("GET", _server_path(server_id) + "/tools")

    def delete(self, server_id: int) -> Any:
        return self._c.request("DELETE", _server_path(server_id))
