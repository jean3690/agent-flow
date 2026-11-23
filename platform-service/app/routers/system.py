from __future__ import annotations

from fastapi import APIRouter

from app.ai_client import get_ai
from app.serialization import ok

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health():
    return ok({"status": "UP", "service": "agent-flow-platform"})


@router.get("/ai-health")
def ai_health():
    return ok({"up": get_ai().healthy()})
