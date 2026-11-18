"""Streamable HTTP MCP clients with per-run credentials and tool allowlists."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import Settings

MAX_RESULT = 200_000
MAX_TOOLS = 100
_HEADER = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$")


def make_http_client(config: McpServerConfig, guard):
    return httpx.AsyncClient(headers=config.headers, timeout=config.timeout_ms / 1000,
                             transport=_LimitedTransport(), follow_redirects=False,
                             trust_env=False, event_hooks={"request": [guard]})


class _LimitedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > 2_000_000:
                raise ValueError("MCP HTTP 响应超过 2 MB 限制")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class _LimitedTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.transport = httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request):
        response = await self.transport.handle_async_request(request)
        return httpx.Response(response.status_code, headers=response.headers,
                              stream=_LimitedStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.transport.aclose()


class McpServerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    url: str = Field(max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list, alias="allowedTools", max_length=100)
    timeout_ms: int = Field(default=15000, alias="timeoutMs", ge=1000, le=60000)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("MCP 仅支持不含账号密码的 HTTP(S) 地址")
        if parsed.query or parsed.fragment:
            raise ValueError("MCP 地址不能包含查询参数或片段；凭据请使用请求头")
        _ = parsed.port
        return value

    @field_validator("headers")
    @classmethod
    def check_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("请求头不能超过 20 项")
        for key, content in value.items():
            if not _HEADER.fullmatch(key) or key.lower() in {"host", "content-length", "connection", "transfer-encoding"}:
                raise ValueError("不允许覆盖连接相关请求头")
            if "\r" in content or "\n" in content or len(content) > 8192:
                raise ValueError("请求头值无效或过长")
        return value


async def validate_target(url: str, settings: Settings) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    exceptions = {item.strip().lower() for item in settings.mcp_private_hosts.split(",") if item.strip()}
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("MCP 地址无法解析") from exc
    if not addresses:
        raise ValueError("MCP 地址没有可连接的 IP")
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global and host.lower() not in exceptions:
            raise ValueError("MCP 默认禁止内网地址；仅部署环境可通过 AI_MCP_PRIVATE_HOSTS 显式允许")


@asynccontextmanager
async def _session(config: McpServerConfig, settings: Settings):
    origin = urlsplit(config.url)
    exceptions = {host.strip().lower() for host in settings.mcp_private_hosts.split(",") if host.strip()}
    if config.headers and origin.scheme != "https" and origin.hostname not in exceptions:
        raise ValueError("公网 MCP 认证必须使用 HTTPS")

    async def guard(request: httpx.Request):
        target = urlsplit(str(request.url))
        if (target.scheme, target.hostname, target.port or (443 if target.scheme == "https" else 80)) != (
            origin.scheme, origin.hostname, origin.port or (443 if origin.scheme == "https" else 80)
        ):
            raise ValueError("MCP 禁止跨源请求或重定向")
        await validate_target(str(request.url), settings)

    await validate_target(config.url, settings)
    async with (
        make_http_client(config, guard) as client,
        streamable_http_client(config.url, http_client=client) as (read, write, _),
        ClientSession(read, write, read_timeout_seconds=timedelta(milliseconds=config.timeout_ms)) as session,
    ):
        await session.initialize()
        yield session


async def _tools(session: ClientSession) -> list[dict]:
    result, seen, cursor, names = [], set(), None, set()
    for _ in range(5):
        page = await session.list_tools(cursor=cursor)
        for tool in page.tools:
            if not tool.name or len(tool.name) > 128 or tool.name in names:
                raise ValueError("MCP 工具名称无效或重复")
            names.add(tool.name)
            result.append({"name": tool.name, "description": tool.description or "", "inputSchema": tool.inputSchema})
            if len(result) > MAX_TOOLS:
                raise ValueError("MCP 工具数量超过 100 项")
        cursor = page.nextCursor
        if not cursor:
            if len(json.dumps(result, ensure_ascii=False)) > MAX_RESULT:
                raise ValueError("MCP 工具声明过大")
            return result
        if cursor in seen:
            raise ValueError("MCP 工具分页游标重复")
        seen.add(cursor)
    raise ValueError("MCP 工具分页超过限制")


async def discover_tools(config: McpServerConfig, settings: Settings) -> list[dict]:
    async with asyncio.timeout(config.timeout_ms / 1000):
        async with _session(config, settings) as session:
            return await _tools(session)


async def call_tool(config: McpServerConfig, tool: str, arguments: dict, settings: Settings) -> dict:
    if tool not in config.allowed_tools:
        raise ValueError("MCP 工具未授权或已禁用")
    if len(json.dumps(arguments, ensure_ascii=False)) > MAX_RESULT:
        raise ValueError("MCP 工具参数过大")
    async with asyncio.timeout(config.timeout_ms / 1000):
        async with _session(config, settings) as session:
            result = await session.call_tool(tool, arguments)
            if result.isError:
                # Do not propagate remote exceptions/headers into execution logs.
                raise ValueError("MCP 工具返回失败，请检查服务端状态与参数")
            content = [item.model_dump(mode="json", by_alias=True) for item in result.content]
            structured = getattr(result, "structuredContent", None)
            text = "\n".join(item.get("text", "") for item in content if item.get("type") == "text")
            payload = {"content": content, "data": structured, "text": text}
            if len(json.dumps(payload, ensure_ascii=False)) > MAX_RESULT:
                raise ValueError("MCP 工具结果过大")
            return payload
