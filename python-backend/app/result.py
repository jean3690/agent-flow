from __future__ import annotations

from typing import Any


def success(data: Any = None) -> dict:
    return {"code": 200, "message": "操作成功", "data": data}


def error(message: str, code: int = 500) -> dict:
    return {"code": code, "message": message, "data": None}
