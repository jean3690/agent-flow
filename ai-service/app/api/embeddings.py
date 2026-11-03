from __future__ import annotations

import hashlib
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(prefix="/v1", tags=["embeddings"])

_MOCK_DIM = 64


class EmbeddingRequest(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    input: list[str] = Field(default_factory=list)
    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="", alias="baseUrl")

    model_config = {"populate_by_name": True}


@router.post("/embeddings")
async def embeddings(request: EmbeddingRequest):
    settings = get_settings()
    texts = [text for text in request.input if text.strip()][:64]
    if not texts:
        return {"data": {"vectors": [], "model": request.model, "dim": 0, "mock": False}}

    provider = (request.provider or "openai").lower()
    api_key = request.api_key.strip() or settings.api_key_for(provider)
    base_url = request.base_url.strip() or settings.base_url_for(provider)

    if provider == "mock" or not api_key:
        return {
            "data": {
                "vectors": [_mock_vector(text) for text in texts],
                "model": "mock-embedding",
                "dim": _MOCK_DIM,
                "mock": True,
            }
        }

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=30)
        response = await client.embeddings.create(model=request.model, input=texts)
        vectors = [item.embedding for item in response.data]
        return {
            "data": {
                "vectors": vectors,
                "model": request.model,
                "dim": len(vectors[0]) if vectors else 0,
                "mock": False,
            }
        }
    except Exception as exc:  # noqa: BLE001 - surface provider errors to the caller
        message = str(exc).replace(api_key, "***")
        raise HTTPException(status_code=502, detail=f"embedding 调用失败: {message[:400]}") from exc


def _mock_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = [digest[index % len(digest)] / 127.5 - 1.0 for index in range(_MOCK_DIM)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 6) for value in values]
