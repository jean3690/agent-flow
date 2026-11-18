"""Literal text processing and CSV import/export; no user code or regex."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.core.template import stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import (
    MAX_CHARS,
    MAX_ITEMS,
    bool_config,
    check_size,
    int_config,
    json_text,
    names_for,
    parse_json,
    render_deep,
    source_value,
)
from app.schemas.flow import FlowNode


@register
class TextProcessNodeExecutor(NodeExecutor):
    type = "text_process"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = source_value(node, state, ctx)
        action = str(node.config.get("action", "trim"))
        items = []
        truncated = False
        if action == "join":
            source = parse_json(source)
            if not isinstance(source, list):
                raise ValueError("拼接操作的数据源必须是数组")
            separator = str(render_deep(node.config.get("separator", "\n"), names_for(state)))
            items = source
            parts = [stringify(item) for item in source]
            if sum(len(part) for part in parts) + max(0, len(parts) - 1) * len(separator) > MAX_CHARS:
                raise ValueError("拼接后的文本超过大小限制")
            value = separator.join(parts)
        else:
            if not isinstance(source, str):
                raise ValueError("文本处理的数据源必须是字符串；数组请使用拼接操作")
            if action == "trim":
                value = source.strip()
            elif action == "lower":
                value = source.lower()
            elif action == "upper":
                value = source.upper()
            elif action == "replace":
                old = str(render_deep(node.config.get("search", ""), names_for(state)))
                replacement = str(render_deep(node.config.get("replacement", ""), names_for(state)))
                if not old:
                    raise ValueError("替换操作的查找文本不能为空")
                count = int_config(node, "replaceCount", -1, -1, MAX_ITEMS)
                # Check expansion before allocating an oversized output string.
                matches = source.count(old)
                if count >= 0:
                    matches = min(matches, count)
                if len(source) + matches * (len(replacement) - len(old)) > MAX_CHARS:
                    raise ValueError("替换后的文本超过大小限制")
                value = source.replace(old, replacement, count)
            elif action == "split":
                separator = str(render_deep(node.config.get("separator", "\n"), names_for(state)))
                if not separator:
                    raise ValueError("拆分分隔符不能为空")
                if source.count(separator) >= MAX_ITEMS:
                    raise ValueError("拆分后的数组不能超过 10,000 项")
                items = source.split(separator)
                if bool_config(node, "removeEmpty", False):
                    items = [item for item in items if item.strip()]
                value = items
            elif action == "truncate":
                limit = int_config(node, "maxLength", 1000, 0, MAX_CHARS)
                value = source[:limit]
                truncated = len(source) > limit
            else:
                raise ValueError(f"不支持的文本操作: {action}")
        check_size(value)
        text = stringify(value)
        return {"value": value, "text": text, "items": items, "count": len(items), "charCount": len(text), "truncated": truncated}


def _columns(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("CSV 列名必须是不含空列名的字符串数组")
    if len(value) != len(set(value)):
        raise ValueError("CSV 不允许重复列名")
    return value


def _safe_cell(value: Any, protect: bool) -> str:
    text = stringify(value)
    if protect and isinstance(value, str) and text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@register
class CsvNodeExecutor(NodeExecutor):
    type = "csv"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = source_value(node, state, ctx)
        action = str(node.config.get("action", "parse"))
        delimiter = str(node.config.get("delimiter", ","))
        if len(delimiter) != 1 or delimiter in {'"', "\r", "\n", "\0"}:
            raise ValueError("CSV 分隔符必须是一个非引号、非换行字符")
        columns = _columns(node.config.get("columns", []))
        has_header = bool_config(node, "hasHeader", True)
        if action == "parse":
            if not isinstance(source, str):
                raise ValueError("CSV 解析的数据源必须是文本")
            reader = csv.reader(io.StringIO(source.lstrip("\ufeff"), newline=""), delimiter=delimiter, strict=True)
            rows = []
            # The process-wide csv.field_size_limit stays untouched.
            for cells in reader:
                if not cells:
                    continue
                if not columns:
                    columns = _columns(cells) if has_header else [f"column_{i + 1}" for i in range(len(cells))]
                    if has_header:
                        has_header = False
                        continue
                elif has_header:
                    if cells != columns:
                        raise ValueError("CSV 表头与配置的列名不一致")
                    has_header = False
                    continue
                if len(cells) != len(columns):
                    raise ValueError(f"CSV 第 {reader.line_num} 行列数与表头不一致")
                rows.append(dict(zip(columns, cells, strict=True)))
                if len(rows) > MAX_ITEMS:
                    raise ValueError("CSV 不能超过 10,000 行")
            return {"rows": rows, "value": rows, "text": json_text(rows), "columns": columns, "count": len(rows)}
        if action != "generate":
            raise ValueError(f"不支持的 CSV 操作: {action}")
        rows = parse_json(source)
        if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
            raise ValueError("CSV 导出的数据源必须是对象数组")
        if not columns:
            columns = _columns(list(dict.fromkeys(key for row in rows for key in row)))
        if len(columns) > MAX_ITEMS:
            raise ValueError("CSV 列数超过限制")
        protect = bool_config(node, "protectFormulas", True)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
        if has_header and columns:
            writer.writerow([_safe_cell(column, protect) for column in columns])
        for row in rows:
            writer.writerow([_safe_cell(row.get(column), protect) for column in columns])
            if buffer.tell() > MAX_CHARS:
                raise ValueError("导出的 CSV 超过大小限制")
        text = buffer.getvalue()
        check_size(text)
        return {"rows": rows, "value": text, "text": text, "columns": columns, "count": len(rows)}
