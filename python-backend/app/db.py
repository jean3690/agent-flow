from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .settings import settings

try:
    os.environ.setdefault("TZ", "Asia/Shanghai")
    time.tzset()
except Exception:  # pragma: no cover - platform dependent
    pass

LOCAL_TZ = ZoneInfo("Asia/Shanghai")

_database_url = settings.database_url()
if _database_url.startswith("sqlite"):
    engine = create_engine(_database_url, connect_args={"check_same_thread": False}, future=True)
else:
    engine = create_engine(
        _database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
        connect_args={"init_command": "SET time_zone = '+08:00'"},
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def format_dt(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def isoformat_dt(value: Any) -> Any:
    return format_dt(value)


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def jload(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def to_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return False


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_text(*values: Any) -> str | None:
    for value in values:
        text = text_or_none(value)
        if text is not None:
            return text
    return None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
