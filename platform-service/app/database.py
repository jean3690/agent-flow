from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, NodeDefinition, User
from app.security import hash_password

log = logging.getLogger("agentflow.db")

_settings = get_settings()


def _normalize_url(url: str) -> str:
    if url.startswith("mysql://"):
        return "mysql+pymysql://" + url[len("mysql://") :]
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        if raw and raw != ":memory:":
            Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    return url


DATABASE_URL = _normalize_url(_settings.database_url)
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine: Engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def seed() -> None:
    settings = get_settings()
    with session_scope() as session:
        admin = session.scalar(select(User).where(User.deleted == 0).limit(1))
        if admin is None:
            session.add(
                User(
                    username=settings.default_username,
                    password=hash_password(settings.default_password),
                    nickname="管理员",
                    role="ADMIN",
                    deleted=0,
                )
            )
            log.info("default admin created: %s", settings.default_username)
        _seed_nodes(session)


def _seed_nodes(session: Session) -> None:
    path = get_settings().resources_dir / "node-definitions.json"
    if not path.exists():
        log.warning("node definitions file missing: %s", path)
        return
    items = json.loads(path.read_text(encoding="utf-8"))
    existing = {item.type: item for item in session.scalars(select(NodeDefinition)).all()}
    for item in items:
        node_type = str(item.get("type", ""))
        if not node_type:
            continue
        entity = existing.get(node_type)
        if entity is None:
            entity = NodeDefinition(type=node_type)
            session.add(entity)
        entity.name = str(item.get("name", ""))
        entity.category = str(item.get("category", ""))
        entity.icon = str(item.get("icon", ""))
        entity.color = str(item.get("color", ""))
        entity.description = str(item.get("description", ""))
        schema = item.get("configSchema")
        entity.config_schema = json.dumps(schema, ensure_ascii=False) if schema is not None else "[]"
        entity.sort = int(item.get("sort", 0) or 0)
        entity.enabled = 1
    log.info("node definitions synced: %d", len(items))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    seed()
