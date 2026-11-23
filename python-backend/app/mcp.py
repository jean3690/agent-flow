from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .db import first_text, format_dt, jdump, jload, now, text_or_none, to_int
from .models import McpToolConfig

logger = logging.getLogger("agentflow.mcp")

AGENT_PLAN_WEB_SEARCH = "agent_plan_web_search"
WEB_SEARCH_TOOL_NAME = "web_search"
SEARCH_API_KEY_ENV = "ASK_ECHO_SEARCH_INFINITY_API_KEY"
SEARCH_INFINITY_PACKAGE = "git+https://github.com/volcengine/mcp-server#subdirectory=server/mcp_server_askecho_search_infinity"
SEARCH_INFINITY_COMMAND = "mcp-server-askecho-search-infinity"
INITIALIZE_TIMEOUT = 90.0
CALL_TIMEOUT = 120.0


def parse_args(config: McpToolConfig) -> list[str]:
    value = jload(config.args, [])
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def parse_env(config: McpToolConfig) -> dict[str, str]:
    value = jload(config.env, {})
    if not isinstance(value, dict):
        return {}
    return {str(key): "" if item is None else str(item) for key, item in value.items()}


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(token in upper for token in ("KEY", "SECRET", "TOKEN", "PASSWORD"))


def mask_env(env: dict[str, str]) -> dict[str, str]:
    return {key: "******" if _is_secret_key(key) else value for key, value in env.items()}


def _to_safe_map(config: McpToolConfig) -> dict:
    return {
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "toolType": config.tool_type,
        "toolName": config.tool_name,
        "transport": config.transport,
        "command": config.command,
        "args": parse_args(config),
        "env": mask_env(parse_env(config)),
        "enabled": config.enabled,
        "preset": config.preset,
        "createdAt": format_dt(config.created_at),
        "updatedAt": format_dt(config.updated_at),
    }


def list_configs(db: Session) -> list[dict]:
    rows = db.execute(
        select(McpToolConfig)
        .where(McpToolConfig.deleted == 0)
        .order_by(McpToolConfig.updated_at.desc())
    ).scalars()
    return [_to_safe_map(row) for row in rows]


def _require_config(db: Session, config_id: int) -> McpToolConfig:
    config = db.execute(
        select(McpToolConfig).where(McpToolConfig.id == config_id, McpToolConfig.deleted == 0)
    ).scalar_one_or_none()
    if config is None:
        raise ValueError("MCP 工具不存在")
    return config


def _apply_request(config: McpToolConfig, payload: dict) -> None:
    name = text_or_none(payload.get("name"))
    tool_name = text_or_none(payload.get("toolName"))
    command = text_or_none(payload.get("command"))
    if not name:
        raise ValueError("MCP 名称不能为空")
    if not tool_name:
        raise ValueError("工具名不能为空")
    if not command:
        raise ValueError("启动命令不能为空")
    config.name = name
    config.description = text_or_none(payload.get("description"))
    config.tool_type = first_text(payload.get("toolType"), "custom")
    config.tool_name = tool_name
    config.transport = first_text(payload.get("transport"), "stdio")
    config.command = command
    config.args = jdump(payload.get("args") or [])
    config.env = jdump(payload.get("env") or {})
    enabled = payload.get("enabled")
    config.enabled = 1 if enabled is None or to_int(enabled, 1) == 1 else 0
    if config.preset is None:
        config.preset = 0


def create_config(db: Session, payload: dict) -> dict:
    config = McpToolConfig()
    config.deleted = 0
    config.preset = 0
    _apply_request(config, payload)
    db.add(config)
    db.commit()
    db.refresh(config)
    return _to_safe_map(config)


def create_agent_plan_web_search(db: Session, payload: dict) -> dict:
    api_key = text_or_none(payload.get("apiKey"))
    if not api_key:
        raise ValueError("联网搜索 API Key 不能为空")
    config = McpToolConfig()
    config.name = first_text(payload.get("name"), "Agent Plan 联网搜索")
    config.description = first_text(payload.get("description"), "通过火山 Agent Plan Harness MCP 使用联网搜索额度")
    config.tool_type = AGENT_PLAN_WEB_SEARCH
    config.tool_name = WEB_SEARCH_TOOL_NAME
    config.transport = "stdio"
    config.command = resolve_default_uvx_command()
    config.args = jdump(["--from", SEARCH_INFINITY_PACKAGE, SEARCH_INFINITY_COMMAND])
    config.env = jdump({SEARCH_API_KEY_ENV: api_key})
    config.enabled = 1
    config.preset = 1
    config.deleted = 0
    db.add(config)
    db.commit()
    db.refresh(config)
    return _to_safe_map(config)


def update_config(db: Session, config_id: int, payload: dict) -> dict:
    config = _require_config(db, config_id)
    _apply_request(config, payload)
    db.commit()
    db.refresh(config)
    return _to_safe_map(config)


def delete_config(db: Session, config_id: int) -> None:
    db.execute(
        update(McpToolConfig).where(McpToolConfig.id == config_id).values(deleted=1, updated_at=now())
    )
    db.commit()


def _parse_ids(raw_ids: Any) -> list[int]:
    if raw_ids is None:
        return []
    values = raw_ids if isinstance(raw_ids, list) else str(raw_ids).split(",")
    ids: list[int] = []
    for value in values:
        parsed = to_int(value)
        if parsed is not None:
            ids.append(parsed)
    return ids


def resolve_enabled_configs(db: Session, raw_ids: Any) -> list[McpToolConfig]:
    ids = _parse_ids(raw_ids)
    if not ids:
        return []
    rows = db.execute(
        select(McpToolConfig).where(
            McpToolConfig.id.in_(ids),
            McpToolConfig.deleted == 0,
        )
    ).scalars()
    return [row for row in rows if (row.enabled or 0) == 1]


def resolve_first_enabled_web_search(db: Session, raw_ids: Any) -> Optional[McpToolConfig]:
    for config in resolve_enabled_configs(db, raw_ids):
        if config.tool_name == WEB_SEARCH_TOOL_NAME:
            return config
    return None


def resolve_default_uvx_command() -> str:
    configured = os.environ.get("MCP_UVX_PATH", "").strip()
    if configured:
        return configured
    user_local = Path.home() / ".local" / "bin" / "uvx"
    if user_local.is_file() and os.access(user_local, os.X_OK):
        return str(user_local)
    return "uvx"


class McpSession:
    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self._request_id = 0
        self._stderr_lines: list[str] = []
        self._lock = threading.Lock()
        self._buffer = b""
        self._stderr_thread = threading.Thread(target=self._collect_stderr, daemon=True)
        self._stderr_thread.start()

    @classmethod
    def start(cls, command: str, args: list[str], env: dict[str, str]) -> "McpSession":
        command_line = [command] + list(args or [])
        process_env = os.environ.copy()
        for key, value in (env or {}).items():
            if key:
                process_env[key] = "" if value is None else str(value)
        process = subprocess.Popen(
            command_line,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=process_env,
        )
        return cls(process)

    def _collect_stderr(self) -> None:
        try:
            assert self.process.stderr is not None
            for raw in self.process.stderr:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                with self._lock:
                    self._stderr_lines.append(line)
                    del self._stderr_lines[:-8]
        except Exception:
            pass

    def _recent_stderr(self) -> str:
        with self._lock:
            return "\n".join(list(self._stderr_lines))

    def _write(self, message: dict) -> None:
        assert self.process.stdin is not None
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n"
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def _read_line(self, deadline: float) -> Optional[str]:
        assert self.process.stdout is not None
        fd = self.process.stdout.fileno()
        while True:
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                line = self._buffer[:newline]
                self._buffer = self._buffer[newline + 1 :]
                return line.decode("utf-8", errors="replace").strip()
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("MCP timeout")
            ready, _, _ = select.select([fd], [], [], remaining)
            if not ready:
                raise TimeoutError("MCP timeout")
            chunk = os.read(fd, 65536)
            if not chunk:
                return None
            self._buffer += chunk

    def _request(self, method: str, params: dict, timeout: float) -> dict:
        self._request_id += 1
        request_id = self._request_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.time() + timeout
        while True:
            line = self._read_line(deadline)
            if line is None:
                raise RuntimeError("MCP server closed stdout")
            if not line:
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") == request_id:
                if response.get("error"):
                    raise RuntimeError(f"MCP 调用失败: {json.dumps(response['error'], ensure_ascii=False)}")
                result = response.get("result")
                return result if isinstance(result, dict) else {}

    def _notify(self, method: str, params: dict) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AgentFlow", "version": "0.1.0"},
            },
            INITIALIZE_TIMEOUT,
        )
        self._notify("notifications/initialized", {})

    def call_tool(self, name: str, arguments: dict) -> dict:
        return self._request("tools/call", {"name": name, "arguments": arguments}, CALL_TIMEOUT)

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            if self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def __enter__(self) -> "McpSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _parse_json_if_possible(text: str) -> Any:
    trimmed = text.strip()
    if not trimmed.startswith("{") and not trimmed.startswith("["):
        return None
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        return None


def _first_map_value(mapping: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _collect_web_results(value: Any, results: list[dict]) -> None:
    if isinstance(value, dict):
        web_results = _first_map_value(value, ("WebResults", "webResults"))
        if isinstance(web_results, list):
            for item in web_results:
                if isinstance(item, dict):
                    results.append(_to_web_result(item))
        for child in value.values():
            _collect_web_results(child, results)
    elif isinstance(value, list):
        for child in value:
            _collect_web_results(child, results)


def _to_web_result(result: dict) -> dict:
    return {
        "id": _first_map_value(result, ("Id", "id")),
        "sortId": _first_map_value(result, ("SortId", "sortId")),
        "title": _first_map_value(result, ("Title", "title")),
        "siteName": _first_map_value(result, ("SiteName", "siteName")),
        "url": _first_map_value(result, ("Url", "url")),
        "snippet": _first_map_value(result, ("Snippet", "snippet")),
        "summary": _first_map_value(result, ("Summary", "summary")),
    }


def _looks_like_url(value: Any) -> bool:
    return isinstance(value, str) and value.lower().startswith(("http://", "https://"))


def _summarize_web_results(web_results: list[dict]) -> str:
    lines: list[str] = []
    for index, result in enumerate(web_results, start=1):
        title = result.get("title") or ""
        site_name = result.get("siteName") or ""
        snippet = first_text(result.get("summary"), result.get("snippet")) or ""
        line = f"{index}. {title}"
        if site_name:
            line += f" - {site_name}"
        if snippet:
            line += f"\n{snippet}"
        lines.append(line)
    return "\n".join(lines).strip()


def _citations_from_web_results(web_results: list[dict]) -> list[dict]:
    citations: list[dict] = []
    for result in web_results:
        url = result.get("url")
        if _looks_like_url(url):
            citations.append(
                {
                    "url": url,
                    "title": result.get("title") or url,
                    "siteName": result.get("siteName") or "",
                }
            )
    return citations


def _collect_citations(value: Any, citations: list[dict]) -> None:
    if isinstance(value, dict):
        url = _first_map_value(value, ("url", "Url", "link", "Link", "site", "Site"))
        if _looks_like_url(url):
            citations.append({"url": url, "title": first_text(value.get("title"), value.get("Title"), url)})
        for child in value.values():
            _collect_citations(child, citations)
    elif isinstance(value, list):
        for child in value:
            _collect_citations(child, citations)


def _find_business_error(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        metadata = _first_map_value(value, ("ResponseMetadata",))
        if isinstance(metadata, dict):
            error = metadata.get("Error")
            if isinstance(error, dict) and error:
                code = error.get("Code")
                message = error.get("Message")
                if code and message:
                    return f"{code}: {message}"
                return first_text(code, message, json.dumps(error, ensure_ascii=False))
        for child in value.values():
            found = _find_business_error(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_business_error(child)
            if found:
                return found
    return None


def _find_first_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_first_value(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first_value(child, key)
            if found is not None:
                return found
    return None


def _normalize_tool_result(result: dict) -> dict:
    is_error = bool(result.get("isError"))
    content = result.get("content") or []
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and "result" in structured:
        structured = structured.get("result")

    parsed_items: list[Any] = []
    summary_parts: list[str] = []
    if structured is not None:
        parsed_items.append(structured)
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not text:
                continue
            summary_parts.append(str(text))
            if structured is None:
                parsed = _parse_json_if_possible(str(text))
                parsed_items.append(parsed if parsed is not None else {"text": text})
    summary = "\n".join(summary_parts)

    if is_error:
        raise RuntimeError(f"联网搜索 MCP 工具返回错误: {summary[:500]}")
    business_error = _find_business_error(parsed_items)
    if business_error:
        raise RuntimeError(f"联网搜索 API 返回错误: {business_error}")

    web_results: list[dict] = []
    _collect_web_results(parsed_items, web_results)
    readable_summary = _summarize_web_results(web_results) if web_results else summary

    request_id = _find_first_value(parsed_items, "RequestId")
    result_count = _find_first_value(parsed_items, "ResultCount")
    if not isinstance(result_count, int):
        result_count = len(web_results)

    citations = _citations_from_web_results(web_results) if web_results else []
    if not citations:
        _collect_citations(parsed_items, citations)

    return {
        "summary": readable_summary,
        "rawSummary": summary,
        "requestId": request_id,
        "resultCount": result_count,
        "webResults": web_results,
        "results": parsed_items,
        "citations": citations,
        "content": content if isinstance(content, list) else [],
        "isError": False,
        "raw": result,
    }


def web_search(
    config: McpToolConfig,
    query: str,
    count: int,
    time_range: Optional[str],
    auth_level: Optional[int],
    search_type: str,
) -> dict:
    if config is None:
        raise ValueError("联网搜索缺少 MCP 工具配置")
    if not query:
        raise ValueError("联网搜索缺少 query")

    command = config.command.strip() if config.command else ""
    if not command or command == "uvx":
        command = resolve_default_uvx_command()
    args = parse_args(config)
    env = parse_env(config)

    try:
        with McpSession.start(command, args, env) as session:
            session.initialize()
            arguments = {
                "Query": query,
                "Count": max(1, min(count, 5 if search_type and search_type.lower() == "image" else 50)),
                "SearchType": search_type or "web",
            }
            if time_range:
                arguments["TimeRange"] = time_range
            if auth_level is not None:
                arguments["AuthLevel"] = auth_level
            logger.info("MCP web_search start: query=%s count=%s", query[:120], arguments["Count"])
            result = session.call_tool(WEB_SEARCH_TOOL_NAME, arguments)
            return _normalize_tool_result(result)
    except TimeoutError as exc:
        raise RuntimeError(
            "联网搜索 MCP 调用超时，请检查 uvx、网络或 mcp-server-askecho-search-infinity 是否可启动"
        ) from exc


def test_config(db: Session, config_id: int, query: Optional[str]) -> dict:
    config = _require_config(db, config_id)
    if config.tool_name != WEB_SEARCH_TOOL_NAME:
        raise ValueError("当前只支持测试 web_search MCP 工具")
    search_query = text_or_none(query) or "今天的科技新闻"
    return web_search(config, search_query, 3, None, None, "web")
