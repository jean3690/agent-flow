from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_client import AiClient, get_ai
from app.errors import BizError, not_found
from app.models import AgentMemory
from app.scoring import cosine, document_frequency, gram_counts, hybrid, lexical_ceiling, lexical_score
from app.security import CurrentUser
from app.serialization import dumps, iso, loads
from app.services.providers import ProviderService

log = logging.getLogger("agentflow.memory")

MAX_CONTENT = 8000
MAX_CANDIDATES = 1000
MAX_TOP_K = 20
MAX_TAGS = 10
MAX_TAG_LENGTH = 32
SCOPES = {"workflow", "user", "global"}


def normalize_tags(tags: list[Any] | None) -> list[str]:
    if not tags:
        return []
    unique: list[str] = []
    for item in tags:
        if item is None:
            continue
        for part in str(item).replace("，", ",").split(","):
            value = part.strip()
            if value and value[:MAX_TAG_LENGTH] not in unique:
                unique.append(value[:MAX_TAG_LENGTH])
            if len(unique) >= MAX_TAGS:
                return unique
    return unique


def parsed_tags(tags: str | None) -> list[str]:
    if not tags or not tags.strip():
        return []
    return [item.strip() for item in tags.split(",") if item.strip()]


def _normalize_scope(scope: str | None) -> str:
    value = (scope or "workflow").strip().lower()
    return value if value in SCOPES else "workflow"


def _normalize_type(value: str | None) -> str:
    text = (value or "fact").strip().lower()
    return (text or "fact")[:32]


def _trim(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:limit]


class MemoryService:
    def __init__(self, providers: ProviderService | None = None, ai: AiClient | None = None) -> None:
        self.providers = providers or ProviderService()
        self.ai = ai or get_ai()

    def write(self, session: Session, payload: dict[str, Any]) -> dict[str, Any]:
        content = (payload.get("content") or "").strip()
        if not content:
            raise BizError("记忆内容不能为空")
        if len(content) > MAX_CONTENT:
            raise BizError(f"记忆内容不能超过 {MAX_CONTENT} 字")
        scope = _normalize_scope(payload.get("scope"))
        workflow_id = payload.get("workflowId")
        user_id = payload.get("userId")
        self._require_scope(scope, workflow_id, user_id)

        vector = self.try_embed(session, payload.get("provider"), payload.get("model"), content)
        entity = AgentMemory(
            workflow_id=workflow_id,
            user_id=user_id,
            scope=scope,
            memory_type=_normalize_type(payload.get("memoryType")),
            content=content,
            tags=",".join(normalize_tags(payload.get("tags"))),
            source_node_id=_trim(payload.get("sourceNodeId"), 64),
            embedding=dumps(vector) if vector is not None else None,
            embedding_model=_trim(payload.get("model"), 64) if vector is not None else None,
        )
        session.add(entity)
        session.flush()
        return {"memoryId": str(entity.id), "scope": scope, "stored": True}

    def search(self, session: Session, payload: dict[str, Any]) -> dict[str, Any]:
        query_text = (payload.get("query") or "").strip()
        if not query_text:
            raise BizError("召回记忆的语句不能为空")
        scope = _normalize_scope(payload.get("scope"))
        workflow_id = payload.get("workflowId")
        user_id = payload.get("userId")
        self._require_scope(scope, workflow_id, user_id)
        top_k = self._clamp(payload.get("topK"), 1, MAX_TOP_K, 5)
        required_tags = normalize_tags(payload.get("tags"))

        query = select(AgentMemory).where(AgentMemory.deleted == 0)
        if scope == "workflow":
            query = query.where(AgentMemory.workflow_id == workflow_id)
        elif scope == "user":
            query = query.where(AgentMemory.user_id == user_id)
        rows = session.scalars(query.order_by(AgentMemory.id.desc()).limit(MAX_CANDIDATES)).all()
        candidates = [row for row in rows if set(required_tags).issubset(set(parsed_tags(row.tags)))]
        if not candidates:
            return {"memories": [], "context": "", "count": 0}

        query_vector = self.try_embed(session, payload.get("provider"), payload.get("model"), query_text)
        query_grams = gram_counts(query_text)
        gram_list = [gram_counts(item.content) for item in candidates]
        frequencies = document_frequency(query_grams, gram_list)
        ceiling = lexical_ceiling(query_grams, len(candidates), frequencies)

        hits: list[dict[str, Any]] = []
        for index, item in enumerate(candidates):
            lexical = lexical_score(query_grams, gram_list[index], len(candidates), frequencies, ceiling)
            score = lexical
            if query_vector is not None:
                stored = loads(item.embedding)
                if isinstance(stored, list) and len(stored) == len(query_vector):
                    score = hybrid(cosine(query_vector, [float(v) for v in stored]), lexical)
            if score <= 0:
                continue
            hits.append(
                {
                    "id": item.id,
                    "workflowId": item.workflow_id,
                    "userId": item.user_id,
                    "scope": item.scope,
                    "memoryType": item.memory_type,
                    "content": item.content,
                    "tags": parsed_tags(item.tags),
                    "sourceNodeId": item.source_node_id,
                    "score": round(score * 1000) / 1000,
                    "createdAt": iso(item.created_at),
                }
            )
        hits.sort(key=lambda hit: hit["score"], reverse=True)
        memories = hits[:top_k]
        context = "\n".join("- " + item["content"] for item in memories).strip()
        return {"memories": memories, "context": context, "count": len(memories)}

    def list_memories(self, session: Session, user: CurrentUser | None, scope: str | None,
                      workflow_id: int | None) -> list[dict[str, Any]]:
        query = select(AgentMemory).where(AgentMemory.deleted == 0)
        if user is not None and not user.is_admin:
            query = query.where((AgentMemory.user_id == user.id) | (AgentMemory.scope == "global"))
        if scope and scope.strip():
            query = query.where(AgentMemory.scope == _normalize_scope(scope))
        if workflow_id is not None:
            query = query.where(AgentMemory.workflow_id == workflow_id)
        rows = session.scalars(query.order_by(AgentMemory.id.desc()).limit(200)).all()
        return [
            {
                "id": item.id,
                "workflowId": item.workflow_id,
                "userId": item.user_id,
                "scope": item.scope,
                "memoryType": item.memory_type,
                "content": item.content,
                "tags": parsed_tags(item.tags),
                "sourceNodeId": item.source_node_id,
                "createdAt": iso(item.created_at),
            }
            for item in rows
        ]

    def delete(self, session: Session, memory_id: int, user: CurrentUser | None) -> None:
        entity = session.scalar(
            select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.deleted == 0)
        )
        if entity is None:
            raise not_found(f"记忆不存在: {memory_id}")
        if user is not None and not user.is_admin and entity.user_id != user.id:
            raise not_found(f"记忆不存在: {memory_id}")
        entity.deleted = 1
        session.flush()

    def try_embed(self, session: Session, provider: str | None, model: str | None, text: str) -> list[float] | None:
        if not provider or not provider.strip() or provider.strip().lower() == "mock":
            return None
        try:
            payload: dict[str, Any] = {
                "provider": provider.strip(),
                "model": (model or "").strip() or "text-embedding-3-small",
                "input": [text],
            }
            credentials = self.providers.credentials(session, provider.strip())
            if credentials is not None:
                payload["apiKey"] = credentials.get("apiKey", "")
                payload["baseUrl"] = credentials.get("baseUrl", "")
            data = (self.ai.post_json("/v1/embeddings", payload) or {}).get("data") or {}
            if data.get("mock"):
                return None
            vector = (data.get("vectors") or [None])[0]
            if not isinstance(vector, list) or not vector:
                return None
            return [float(value) for value in vector]
        except Exception as exc:  # noqa: BLE001
            log.warning("memory embedding failed, fallback to lexical: %s", exc)
            return None

    @staticmethod
    def _require_scope(scope: str, workflow_id: int | None, user_id: int | None) -> None:
        if scope == "workflow" and workflow_id is None:
            raise BizError("工作流范围的记忆缺少 workflowId")
        if scope == "user" and user_id is None:
            raise BizError("用户范围的记忆缺少 userId")

    @staticmethod
    def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
        if value is None:
            return fallback
        try:
            number = int(value)
        except (TypeError, ValueError):
            return fallback
        return max(minimum, min(maximum, number))
