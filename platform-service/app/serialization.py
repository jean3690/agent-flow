from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def money(value: Decimal | float | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_default)


def _default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def loads(text: str | None, fallback: Any = None) -> Any:
    if text is None or not text.strip():
        return fallback
    try:
        return json.loads(text)
    except ValueError:
        return fallback


def prune(value: Any) -> Any:
    """Drop null object fields the way Jackson's non_null inclusion does."""
    if isinstance(value, dict):
        return {key: prune(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [prune(item) for item in value]
    return value


def ok(data: Any = None) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": prune(data)}


def page(records: list[Any], total: int, current: int, size: int) -> dict[str, Any]:
    return {"records": records, "total": total, "page": current, "size": size}
