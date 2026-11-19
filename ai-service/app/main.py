from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import catalog, embeddings, executions, files, health, mcp, providers, skills, translations
from app.config import get_settings
from app.core.errors import AgentFlowError
from app.core.logging import setup_logging
from app.skills.registry import get_skill_registry

setup_logging()
settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI):
    get_skill_registry().reload()
    yield


app = FastAPI(
    title="AgentFlow AI Service",
    version="0.1.0",
    description="LangGraph workflow runtime: compile a workflow JSON into a state graph and stream node events.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(skills.router)
app.include_router(providers.router)
app.include_router(embeddings.router)
app.include_router(executions.router)
app.include_router(files.router)
app.include_router(mcp.router)
app.include_router(translations.router)


@app.exception_handler(AgentFlowError)
async def _agentflow_error(_: Request, exc: AgentFlowError):
    return JSONResponse(status_code=400, content={"code": exc.code, "message": exc.message, "detail": exc.detail})


@app.get("/")
async def root():
    return {"service": "agent-flow-ai", "docs": "/docs", "health": "/health"}


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})
