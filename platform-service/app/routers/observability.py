from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app import metrics
from app.ai_client import get_ai
from app.database import session_scope

router = APIRouter(tags=["observability"])


@router.get("/actuator/health")
def actuator_health():
    return {"status": "UP"}


@router.get("/actuator/health/liveness")
def liveness():
    return {"status": "UP"}


@router.get("/actuator/health/readiness")
def readiness():
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "DOWN"})
    if not get_ai().healthy():
        return JSONResponse(status_code=503, content={"status": "DOWN"})
    return {"status": "UP"}


@router.get("/actuator/prometheus", response_class=PlainTextResponse)
def prometheus():
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")
