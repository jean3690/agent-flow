from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_client import AiClient, get_ai
from app.errors import BizError, not_found
from app.models import McpServer
from app.security import CryptoService, CurrentUser
from app.serialization import dumps

HEADER_PATTERN = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
BLOCKED_HEADERS = {"host", "connection", "content-length", "transfer-encoding"}


class McpService:
    def __init__(self, crypto: CryptoService | None = None, ai: AiClient | None = None) -> None:
        self.crypto = crypto or CryptoService()
        self.ai = ai or get_ai()

    def list_servers(self, session: Session, user: CurrentUser) -> list[dict[str, Any]]:
        query = select(McpServer)
        if not user.is_admin:
            query = query.where(McpServer.user_id == user.id)
        rows = session.scalars(query.order_by(McpServer.id.desc())).all()
        return [self._view(item) for item in rows]

    def save(self, session: Session, server_id: int | None, payload: dict[str, Any],
             user: CurrentUser) -> dict[str, Any]:
        self._validate(payload)
        server = McpServer() if server_id is None else self._require(session, server_id, user)
        tools = self._read(server.tools, [])
        available = {str(item.get("name") or "") for item in tools if isinstance(item, dict)}
        allowed_tools = [str(item) for item in (payload.get("allowedTools") or [])]
        if not set(allowed_tools).issubset(available):
            raise BizError("请先测试连接，再从已发现的工具中选择授权项")
        if server_id is None:
            server.user_id = user.id
            server.tools = "[]"
        server.name = str(payload.get("name") or "").strip()
        old_url = server.url
        server.url = str(payload.get("url") or "").strip()
        if old_url is not None and old_url != server.url:
            server.headers_cipher = None
            server.tools = "[]"
            if allowed_tools:
                raise BizError("地址变更后需重新发现并授权工具")
        if payload.get("clearHeaders"):
            server.headers_cipher = None
        headers = payload.get("headers")
        if isinstance(headers, dict) and headers:
            server.headers_cipher = self.crypto.encrypt(dumps(headers))
        deduped: list[str] = []
        for item in allowed_tools:
            if item not in deduped:
                deduped.append(item)
        server.allowed_tools = dumps(deduped)
        server.timeout_ms = int(payload.get("timeoutMs") or 15000)
        server.enabled = 1 if payload.get("enabled", True) else 0
        if server_id is None:
            session.add(server)
        session.flush()
        return self._view(server)

    def delete(self, session: Session, server_id: int, user: CurrentUser) -> None:
        server = self._require(session, server_id, user)
        session.delete(server)

    def discover(self, session: Session, server_id: int, user: CurrentUser) -> Any:
        server = self._require(session, server_id, user)
        result = (self.ai.post_json("/v1/mcp/discover", self._credentials(server)) or {}).get("data") or {}
        if result.get("ok"):
            tools = result.get("tools")
            text = dumps(tools)
            if not isinstance(tools, list) or len(tools) > 100 or len(text) > 200000:
                raise BizError("MCP 工具声明无效或过大")
            condition = [McpServer.id == server_id, McpServer.url == server.url]
            if server.headers_cipher is None:
                condition.append(McpServer.headers_cipher.is_(None))
            else:
                condition.append(McpServer.headers_cipher == server.headers_cipher)
            current = session.scalar(select(McpServer).where(*condition))
            if current is None:
                raise BizError("配置已变更，请重新测试连接")
            current.tools = text
            session.flush()
        return result

    def tools(self, session: Session, server_id: int, user: CurrentUser) -> list[Any]:
        server = self._require(session, server_id, user)
        allowed = {str(item) for item in self._read(server.allowed_tools, [])}
        return [
            item
            for item in self._read(server.tools, [])
            if isinstance(item, dict) and str(item.get("name") or "") in allowed
        ]

    def for_run(self, session: Session, flows: list[dict[str, Any]], user: CurrentUser) -> dict[str, Any]:
        ids: list[int] = []
        for flow in flows:
            for node in flow.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                if node.get("type") == "mcp_tool":
                    value = self._server_id(config.get("serverId"))
                    if value not in ids:
                        ids.append(value)
                elif node.get("type") == "react_agent":
                    selected = config.get("mcpServerIds")
                    if selected is not None and not isinstance(selected, list):
                        raise BizError("mcpServerIds 必须是数组")
                    for value in selected or []:
                        item = self._server_id(value)
                        if item not in ids:
                            ids.append(item)
        result: dict[str, Any] = {}
        for server_id in ids:
            server = self._require(session, server_id, user)
            if server.enabled != 1:
                raise BizError("MCP 服务已禁用")
            result[str(server_id)] = self._credentials(server)
        for flow in flows:
            for node in flow.get("nodes") or []:
                if not isinstance(node, dict) or node.get("type") != "mcp_tool":
                    continue
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                entry = result.get(str(self._server_id(config.get("serverId")))) or {}
                allowed = {str(item) for item in entry.get("allowedTools") or []}
                if str(config.get("toolName") or "") not in allowed:
                    raise BizError("MCP 工具未授权")
        return result

    def _require(self, session: Session, server_id: int, user: CurrentUser) -> McpServer:
        server = session.get(McpServer, server_id)
        if server is None or (not user.is_admin and server.user_id != user.id):
            raise not_found("MCP 服务不存在")
        return server

    def _credentials(self, server: McpServer) -> dict[str, Any]:
        cipher = server.headers_cipher
        return {
            "url": server.url,
            "headers": self._read(self.crypto.decrypt(cipher) if cipher else None, {}),
            "allowedTools": self._read(server.allowed_tools, []),
            "timeoutMs": server.timeout_ms,
        }

    def _view(self, server: McpServer) -> dict[str, Any]:
        return {
            "id": server.id,
            "name": server.name,
            "url": server.url,
            "enabled": server.enabled == 1,
            "timeoutMs": server.timeout_ms,
            "hasCredentials": bool(server.headers_cipher and server.headers_cipher.strip()),
            "allowedTools": self._read(server.allowed_tools, []),
            "tools": self._read(server.tools, []),
        }

    @staticmethod
    def _validate(payload: dict[str, Any]) -> None:
        name = str(payload.get("name") or "")
        url = str(payload.get("url") or "")
        if not name.strip() or len(name) > 128:
            raise BizError("名称不能为空且不能超过 128 字")
        if len(url) > 2048:
            raise BizError("地址过长")
        try:
            parsed = urlparse(url.strip())
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
        except ValueError as exc:
            raise BizError("MCP 只支持不含账号密码、查询参数的 HTTP(S) 地址") from exc
        headers = payload.get("headers")
        if headers is not None:
            if not isinstance(headers, dict):
                raise BizError("请求头无效")
            if len(dumps(headers)) > 20000:
                raise BizError("请求头过大")
            for key, value in headers.items():
                if (
                    not isinstance(key, str)
                    or not HEADER_PATTERN.match(key)
                    or key.lower() in BLOCKED_HEADERS
                    or value is None
                    or "\r" in str(value)
                    or "\n" in str(value)
                    or len(str(value)) > 8192
                ):
                    raise BizError("请求头无效")
        for item in payload.get("allowedTools") or []:
            if not isinstance(item, str) or not item.strip() or len(item) > 128:
                raise BizError("工具名称无效")

    @staticmethod
    def _server_id(value: Any) -> int:
        try:
            number = int(str(value))
            if number > 0:
                return number
        except (TypeError, ValueError):
            pass
        raise BizError("请配置有效的 MCP 服务 ID")

    @staticmethod
    def _read(text: str | None, fallback: Any) -> Any:
        if text is None or not str(text).strip():
            return fallback
        try:
            return json.loads(text)
        except ValueError as exc:
            raise BizError("MCP 配置数据损坏") from exc
