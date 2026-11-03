from __future__ import annotations

from fastapi import APIRouter

from app.catalog import node_catalog
from app.config import get_settings
from app.llm.providers import list_models

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.get("/nodes")
async def nodes():
    return {"data": node_catalog()}


@router.get("/models")
async def models():
    settings = get_settings()
    return {"data": list_models(lambda provider: bool(settings.api_key_for(provider)))}
