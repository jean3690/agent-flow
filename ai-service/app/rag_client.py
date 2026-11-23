"""RAG 节点共用：知识库检索、片段归一化与 RRF 融合。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.graph.context import NodeContext

MAX_CHUNKS = 20


async def search_knowledge(ctx: NodeContext, knowledge_base_id: str, query: str,
                           top_k: int = 4) -> list[dict[str, Any]]:
    base_url = ctx.settings.platform_service_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{base_url}/internal/knowledge/search",
            json={"knowledgeBaseId": knowledge_base_id, "query": query, "topK": top_k},
            headers={"X-Internal-Token": ctx.settings.internal_token},
        )
        response.raise_for_status()
        data = (response.json() or {}).get("data") or {}
    return normalize_chunks(data.get("chunks"))


def normalize_chunks(value: Any, limit: int = MAX_CHUNKS) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, dict):
        value = value.get("chunks")
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:limit]:
        if isinstance(item, str):
            result.append({"chunkId": None, "title": "", "content": item, "score": None})
            continue
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or item.get("text") or "").strip()
        if not content:
            continue
        result.append({
            "chunkId": item.get("chunkId") or item.get("chunk_id"),
            "documentId": item.get("documentId") or item.get("document_id"),
            "title": str(item.get("title") or ""),
            "content": content,
            "score": item.get("score"),
        })
    return result


def chunk_key(chunk: dict[str, Any]) -> str:
    if chunk.get("chunkId") is not None:
        return "id:" + str(chunk["chunkId"])
    return "text:" + str(chunk.get("documentId") or "") + ":" + chunk["content"][:80]


def rrf_merge(groups: list[tuple[str, list[dict[str, Any]]]], top_k: int = 5,
              k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion：同一片段在多路召回中排名越靠前，累计分越高。"""
    merged: dict[str, dict[str, Any]] = {}
    for query, chunks in groups:
        for rank, chunk in enumerate(chunks):
            key = chunk_key(chunk)
            entry = merged.setdefault(key, {
                **chunk,
                "rrfScore": 0.0,
                "matchedQueries": [],
            })
            entry["rrfScore"] += 1.0 / (k + rank + 1)
            if query not in entry["matchedQueries"]:
                entry["matchedQueries"].append(query)
    ordered = sorted(merged.values(), key=lambda item: item["rrfScore"], reverse=True)[:top_k]
    for item in ordered:
        item["rrfScore"] = round(item["rrfScore"], 5)
    return ordered


def chunks_to_text(chunks: list[dict[str, Any]], max_chars: int = 12000) -> str:
    return "\n\n".join(str(item.get("content") or "") for item in chunks)[:max_chars]
