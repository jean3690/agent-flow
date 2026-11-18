"""Timezone-aware date operations and encoding/digest utilities."""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import (
    check_size,
    is_number,
    names_for,
    render_deep,
    source_value,
)
from app.schemas.flow import FlowNode


def _date(value: Any, timezone: ZoneInfo, input_format: str) -> datetime:
    if is_number(value):
        return datetime.fromtimestamp(value, UTC).astimezone(timezone)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("日期必须是 ISO 文本或 Unix 秒级时间戳")
    date = datetime.strptime(value.strip(), input_format) if input_format else datetime.fromisoformat(value.strip())
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone)
        # Reject nonexistent wall-clock times during a DST jump.
        if date.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) != date.replace(tzinfo=None):
            raise ValueError("该本地时间在所选时区不存在")
    return date.astimezone(timezone)


@register
class DateTimeNodeExecutor(NodeExecutor):
    type = "date_time"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        timezone_name = str(node.config.get("timezone", "Asia/Shanghai"))
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区: {timezone_name}") from exc
        action = str(node.config.get("action", "now"))
        if action not in {"now", "format", "add", "diff"}:
            raise ValueError(f"不支持的日期操作: {action}")
        input_format = str(node.config.get("inputFormat") or "")
        output_format = str(node.config.get("outputFormat", "%Y-%m-%d %H:%M:%S"))
        if len(input_format) > 200 or len(output_format) > 200:
            raise ValueError("日期格式不能超过 200 字符")
        date = datetime.now(timezone) if action == "now" else _date(source_value(node, state, ctx), timezone, input_format)
        difference = None
        if action == "add":
            offset = render_deep(node.config.get("offset", 0), names_for(state))
            if isinstance(offset, str):
                offset = float(offset)
            unit = str(node.config.get("unit", "days"))
            units = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}
            if unit not in units or not is_number(offset) or abs(offset * units[unit]) > 315_360_000:
                raise ValueError("日期偏移单位无效或超过十年范围")
            date = (date.astimezone(UTC) + timedelta(seconds=offset * units[unit])).astimezone(timezone)
        elif action == "diff":
            if "end" not in node.config or node.config["end"] == "":
                raise ValueError("计算时间差必须配置结束时间")
            end = _date(source_value(node, state, ctx, "end"), timezone, input_format)
            difference = (end.astimezone(UTC) - date.astimezone(UTC)).total_seconds()
        iso = date.isoformat()
        return {
            "value": difference if action == "diff" else iso,
            "text": str(difference) if action == "diff" else date.strftime(output_format),
            "iso": iso, "timestamp": date.timestamp(), "timezone": timezone_name,
            "differenceSeconds": difference,
        }


@register
class EncodeNodeExecutor(NodeExecutor):
    type = "encode"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        source = source_value(node, state, ctx)
        if not isinstance(source, str):
            raise TypeError("编码与摘要的数据源必须是字符串")
        action = str(node.config.get("action", "sha256"))
        raw = source.encode("utf-8")
        if action == "base64_encode":
            text = base64.b64encode(raw).decode("ascii")
        elif action == "base64_decode":
            text = base64.b64decode(source.encode("ascii"), validate=True).decode("utf-8")
        elif action == "url_encode":
            text = quote(source, safe="")
        elif action == "url_decode":
            if re.search(r"%(?![0-9a-fA-F]{2})", source):
                raise ValueError("URL 包含无效的百分号编码")
            text = unquote(source, encoding="utf-8", errors="strict")
        elif action in {"sha256", "sha512"}:
            text = hashlib.new(action, raw).hexdigest()
        else:
            raise ValueError(f"不支持的编码操作: {action}")
        check_size(text)
        return {"value": text, "text": text, "action": action, "charCount": len(text)}
