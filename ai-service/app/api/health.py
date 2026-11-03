from __future__ import annotations

import time

from fastapi import APIRouter

from app.config import get_settings
from app.llm.providers import PROVIDERS
from app.nodes.registry import registered_types

router = APIRouter(tags=["system"])
_STARTED = time.time()


@router.get("/health")
async def health():
    settings = get_settings()
    configured = [key for key in PROVIDERS if settings.api_key_for(key)]
    return {
        "status": "UP",
        "service": "agent-flow-ai",
        "uptimeSeconds": int(time.time() - _STARTED),
        "mockMode": settings.mock_mode,
        "providers": len(PROVIDERS),
        "configuredProviders": configured,
        "nodeTypes": registered_types(),
    }
