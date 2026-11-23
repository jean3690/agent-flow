from __future__ import annotations

import faulthandler
import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import get_settings
from app.database import init_db
from app.errors import BizError
from app.middleware import PlatformMiddleware
from app.routers import (
    api_keys,
    approvals,
    auth,
    executions,
    files,
    internal,
    knowledge,
    mcp,
    memory,
    node_definitions,
    observability,
    providers,
    skills,
    system,
    translations,
    triggers,
)
from app.routers import workflows as workflow_routes
from app.services.execution import get_execution_service
from app.services.scheduler import get_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
faulthandler.register(signal.SIGUSR1)
log = logging.getLogger("agentflow")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    get_execution_service().recover_stale()
    get_scheduler().start()
    log.info("agent-flow platform service ready on :%s", settings.server_port)
    try:
        yield
    finally:
        get_scheduler().stop()


app = FastAPI(
    title="Agent Flow API",
    version="1.0.0",
    description=(
        "工作流编排与执行服务。提供工作流 CRUD、知识库检索、技能管理、以及工作流的同步/流式执行。"
        "可被外部程序直接调用：鉴权支持 API Key（请求头 X-API-Key）或服务账号 JWT（Authorization: Bearer）。"
        "所有接口统一返回 { code: 0 表示成功, message, data }。"
    ),
    lifespan=lifespan,
)

app.add_middleware(PlatformMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
    max_age=3600,
)

for module in (
    auth,
    workflow_routes,
    executions,
    triggers,
    node_definitions,
    system,
    knowledge,
    memory,
    providers,
    mcp,
    skills,
    files,
    approvals,
    api_keys,
    internal,
    translations,
    observability,
):
    app.include_router(module.router)


@app.exception_handler(BizError)
async def _biz_error(_: Request, exc: BizError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status, content={"code": exc.code, "message": exc.message, "data": exc.data}
    )


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    messages = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", []) if part not in {"body", "query", "path"}]
        messages.append(" ".join([*location, str(error.get("msg", ""))]).strip())
    return JSONResponse(status_code=400, content={"code": 4000, "message": "; ".join(messages), "data": None})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"code": 5000, "message": str(exc), "data": None})


@app.get("/swagger-ui.html", include_in_schema=False)
def swagger_redirect():
    return RedirectResponse(url="/docs")


@app.get("/v3/api-docs", include_in_schema=False)
def openapi_compat():
    return JSONResponse(app.openapi())


@app.get("/", include_in_schema=False)
def root():
    return {"service": "agent-flow-platform", "docs": "/docs", "health": "/api/system/health"}
