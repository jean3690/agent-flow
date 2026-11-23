from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import seed
from .db import Base, SessionLocal, engine
from .routers import auth, executions, knowledge, llm_config, mcp_tools, media, node_definitions, skills, workflows
from .security import auth_service
from .settings import BASE_DIR, settings

try:
    os.environ.setdefault("TZ", "Asia/Shanghai")
    time.tzset()
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("agentflow")

EXCLUDED_PATHS = {
    "/api/auth/login",
    "/api/auth/refresh",
    "/api/auth/current",
    "/api/node-types",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/swagger-ui.html",
    "/v3/api-docs",
}


def _ensure_database() -> None:
    import pymysql

    try:
        connection = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_username,
            password=settings.mysql_password,
            database=settings.mysql_database,
            connect_timeout=5,
        )
        connection.close()
        return
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == 1049:
            connection = pymysql.connect(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_username,
                password=settings.mysql_password,
                connect_timeout=5,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            connection.commit()
            connection.close()
            logger.info("Created database %s", settings.mysql_database)
            return
        raise


def _table_exists(table_name: str) -> bool:
    import pymysql

    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_username,
        password=settings.mysql_password,
        database=settings.mysql_database,
        connect_timeout=5,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (settings.mysql_database, table_name),
            )
            return int(cursor.fetchone()[0]) > 0
    finally:
        connection.close()


def _apply_schema_sql() -> None:
    import pymysql

    schema_path = settings.resolve_schema_sql_path()
    if not schema_path.is_file():
        logger.warning("schema.sql not found at %s", schema_path)
        return
    statements: list[str] = []
    for raw in schema_path.read_text(encoding="utf-8").split(";"):
        lines = [line for line in raw.splitlines() if line.strip() and not line.strip().startswith("--")]
        statement = "\n".join(lines).strip()
        if not statement:
            continue
        upper = statement.upper()
        if upper.startswith("CREATE DATABASE") or upper.startswith("USE "):
            continue
        statements.append(statement)

    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_username,
        password=settings.mysql_password,
        database=settings.mysql_database,
        connect_timeout=5,
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        connection.commit()
        logger.info("Applied schema.sql to %s", settings.mysql_database)
    finally:
        connection.close()


def bootstrap() -> None:
    if not settings.database_url_override.startswith("sqlite"):
        _ensure_database()
        if not _table_exists("workflow"):
            _apply_schema_sql()
    Base.metadata.create_all(engine)
    if settings.auto_migrate:
        db = SessionLocal()
        try:
            seed.seed_node_definitions(db)
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    yield


app = FastAPI(title="AgentFlow API", version="1.0.0", lifespan=lifespan)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    if not path.startswith("/api/"):
        return await call_next(request)
    if path in EXCLUDED_PATHS:
        return await call_next(request)

    authorization = request.headers.get("Authorization")
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = request.query_params.get("token")
    if not token or not auth_service.validate_token(token):
        return JSONResponse(
            status_code=401,
            content={"code": 401, "message": "未认证或认证已过期"},
        )
    return await call_next(request)


# Add CORS last so it wraps the auth middleware and also decorates 401 responses.
_origin_patterns = [pattern.strip() for pattern in settings.cors_allowed_origin_patterns.split(",") if pattern.strip()]
_regex_parts = [r"http://localhost:\d+", r"http://127\.0\.0\.1:\d+"]
for pattern in _origin_patterns:
    escaped = pattern.replace(".", r"\.").replace("*", r".*")
    _regex_parts.append(escaped)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_origin_regex="|".join(f"(?:{part})" for part in _regex_parts),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    message = errors[0].get("msg") if errors else "请求参数不合法"
    return JSONResponse(status_code=400, content={"code": 400, "message": message})


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return JSONResponse(status_code=404, content={"code": 404, "message": "Not Found"})
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"code": 500, "message": str(exc)})


app.include_router(auth.router)
app.include_router(workflows.router)
app.include_router(executions.router)
app.include_router(node_definitions.router)
app.include_router(llm_config.router)
app.include_router(skills.router)
app.include_router(knowledge.router)
app.include_router(mcp_tools.router)
app.include_router(media.router)

_audio_dir = Path("audio_output")
_audio_dir.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(_audio_dir)), name="audio")
