"""File-IO workflow nodes: read, write and list files inside the storage root."""

from __future__ import annotations

import json
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.storage import (
    StorageError,
    list_files,
    read_text,
    save_text,
)
from app.core.template import build_names, render, stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor, extract_value
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_PATH_KEYS = ("path", "filePath", "fileName", "name", "file")
_CONTENT_KEYS = ("content", "text", "data", "body")


def _config_value(config: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = config.get(key)
        if value is not None and value != "":
            return value
    return None


def _render_path(config: dict[str, Any], names: dict[str, Any], default: str = "") -> str:
    raw = _config_value(config, _PATH_KEYS)
    if raw is None or raw == "":
        raw = default
    return render(stringify(raw), names, strict=True).strip()


def _upstream_file_ref(state: FlowState) -> str:
    for value in reversed(list((state.get("outputs") or {}).values())):
        if not isinstance(value, dict):
            continue
        for key in ("path", "fileName", "fileUrl", "url", "imageUrl", "audioUrl", "videoUrl"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                if key in {"imageUrl", "audioUrl", "videoUrl", "url"} and candidate.startswith("/files/"):
                    return candidate.removeprefix("/files/")
                if key == "url" and not candidate.startswith("/files/"):
                    continue
                return candidate
    return ""


def _upstream_content(state: FlowState, node_id: str) -> str:
    outputs = state.get("outputs") or {}
    for current in reversed(state.get("executed") or []):
        if current == node_id or current not in outputs:
            continue
        return stringify(extract_value(outputs[current]))
    return ""


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


@register
class FileReadNodeExecutor(NodeExecutor):
    type = "file_read"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        path = _render_path(config, names) or _upstream_file_ref(state)
        if not path:
            raise NodeExecutionError(node.id, "文件读取节点缺少 path")

        encoding = str(config.get("encoding") or "utf-8")
        raw_limit = config.get("maxChars", config.get("max_chars", ctx.settings.max_read_chars))
        try:
            max_chars = int(raw_limit)
        except (TypeError, ValueError):
            max_chars = ctx.settings.max_read_chars

        try:
            result = read_text(ctx.settings, path, encoding=encoding, max_chars=max_chars)
        except StorageError as exc:
            raise NodeExecutionError(node.id, str(exc)) from exc

        ctx.emit(
            "node_log",
            nodeId=node.id,
            level="info",
            message=f"读取文件 {result['path']}（{result['size']} 字节）",
        )
        return result


@register
class FileWriteNodeExecutor(NodeExecutor):
    type = "file_write"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        path = _render_path(config, names, default=f"output-{node.id}.txt")

        raw_content = _config_value(config, _CONTENT_KEYS)
        if raw_content is None:
            content = _upstream_content(state, node.id)
        elif isinstance(raw_content, str):
            content = render(raw_content, names)
        else:
            content = stringify(raw_content)

        encoding = str(config.get("encoding") or "utf-8")
        append = _bool(config.get("append"), False)
        overwrite = _bool(config.get("overwrite"), True)

        try:
            metadata = save_text(
                ctx.settings,
                content,
                name=path,
                encoding=encoding,
                overwrite=overwrite,
                append=append,
            )
        except StorageError as exc:
            raise NodeExecutionError(node.id, str(exc)) from exc

        metadata.update(
            {
                "text": content,
                "content": content,
                "charCount": len(content),
                "appended": append,
            }
        )
        ctx.emit(
            "node_log",
            nodeId=node.id,
            level="info",
            message=f"写入文件 {metadata['path']}（{metadata['size']} 字节）",
        )
        return metadata


@register
class FileListNodeExecutor(NodeExecutor):
    type = "file_list"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        prefix = render(str(config.get("prefix") or ""), names).strip()
        try:
            limit = max(1, min(int(config.get("limit") or 200), 5000))
        except (TypeError, ValueError):
            limit = 200
        try:
            items = list_files(ctx.settings, prefix=prefix, limit=limit)
        except StorageError as exc:
            raise NodeExecutionError(node.id, str(exc)) from exc
        text = json.dumps(items, ensure_ascii=False)
        return {"files": items, "count": len(items), "text": text, "value": text}


@register
class FileNodeExecutor(NodeExecutor):
    """Generic ``file`` node kept for backward/forward compatibility.

    ``config.action`` may be ``read`` (default), ``write`` or ``list``.
    """

    type = "file"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        action = str(config.get("action") or "read").strip().lower()
        if action in {"write", "save", "append"}:
            if action == "append" and "append" not in config:
                config = {**config, "append": True}
                node = node.model_copy(update={"config": config})
            return await FileWriteNodeExecutor().execute(node, state, ctx)
        if action in {"list", "ls", "dir"}:
            return await FileListNodeExecutor().execute(node, state, ctx)
        return await FileReadNodeExecutor().execute(node, state, ctx)
