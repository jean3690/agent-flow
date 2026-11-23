from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai_client import AiClient, get_ai
from app.errors import BizError, not_found
from app.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.scoring import cosine, document_frequency, gram_counts, hybrid, lexical_ceiling, lexical_score
from app.security import CurrentUser
from app.serialization import dumps, iso, loads
from app.services.providers import ProviderService

log = logging.getLogger("agentflow.knowledge")

MAX_TOP_K = 10
EMBED_BATCH = 16


def split(content: str | None, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    if content is None:
        return chunks
    text = content.replace("\r\n", "\n").strip()
    if not text:
        return chunks
    length = len(text)
    start = 0
    while start < length:
        if start > 0:
            probe = min(length, start + 80)
            for index in range(start + 1, probe + 1):
                if _is_boundary(text[index - 1]):
                    start = index
                    break
            if start >= length:
                break
        end = min(start + size, length)
        if end < length:
            floor = start + max(1, size // 3)
            for index in range(end, floor, -1):
                if _is_boundary(text[index - 1]):
                    end = index
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def _is_boundary(current: str) -> bool:
    return current in "\n。！？；;"


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    if value is None:
        return fallback
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


class KnowledgeService:
    def __init__(self, providers: ProviderService | None = None, ai: AiClient | None = None) -> None:
        self.providers = providers or ProviderService()
        self.ai = ai or get_ai()

    def list_bases(self, session: Session, user: CurrentUser | None) -> list[dict[str, Any]]:
        query = select(KnowledgeBase).where(KnowledgeBase.deleted == 0)
        if user is not None and not user.is_admin:
            query = query.where(KnowledgeBase.user_id == user.id)
        rows = session.scalars(query.order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id.desc())).all()
        return [self._to_vo(session, item) for item in rows]

    def detail(self, session: Session, base_id: int, user: CurrentUser | None) -> dict[str, Any]:
        return self._to_vo(session, self._owned(session, base_id, user))

    def create(self, session: Session, payload: dict[str, Any], user: CurrentUser | None) -> dict[str, Any]:
        name = (payload.get("name") or "").strip()
        if not name:
            raise BizError("知识库名称不能为空")
        chunk_size = _clamp(payload.get("chunkSize"), 200, 2000, 600)
        chunk_overlap = _clamp(payload.get("chunkOverlap"), 0, chunk_size // 2, 80)
        entity = KnowledgeBase(
            name=name,
            description=payload.get("description") or "",
            embedding_provider=payload.get("embeddingProvider") or "mock",
            embedding_model=payload.get("embeddingModel") or "text-embedding-3-small",
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            user_id=user.id if user else None,
        )
        session.add(entity)
        session.flush()
        return self._to_vo(session, entity)

    def delete(self, session: Session, base_id: int, user: CurrentUser | None) -> None:
        entity = self._owned(session, base_id, user)
        for chunk in session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == entity.id)
        ).all():
            session.delete(chunk)
        for document in session.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.knowledge_base_id == entity.id)
        ).all():
            session.delete(document)
        session.delete(entity)

    def documents(self, session: Session, base_id: int, user: CurrentUser | None) -> list[dict[str, Any]]:
        self._owned(session, base_id, user)
        rows = session.scalars(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.deleted == 0)
            .order_by(KnowledgeDocument.id.desc())
        ).all()
        return [self._doc_vo(item) for item in rows]

    def import_text(self, session: Session, base_id: int, title: str | None, content: str | None,
                    source_type: str, user: CurrentUser | None) -> dict[str, Any]:
        self._owned(session, base_id, user)
        return self._import_text(session, base_id, title, content, source_type)

    def upload_text_file(self, session: Session, base_id: int, filename: str | None, content: bytes,
                         user: CurrentUser | None) -> dict[str, Any]:
        self._owned(session, base_id, user)
        if not content:
            raise BizError("请选择文件")
        name = filename or "uploaded.txt"
        lower = name.lower()
        if not lower.endswith((".txt", ".md", ".markdown")):
            raise BizError("目前仅支持 txt / md 文件")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BizError(f"读取文件失败: {exc}") from exc
        return self._import_text(session, base_id, name, text, "FILE")

    def upsert_for_runtime(self, session: Session, base_id: int, title: str | None,
                           content: str | None) -> dict[str, Any]:
        self._get(session, base_id)
        body = (content or "").strip()
        if not body:
            raise BizError("文档内容不能为空")
        if len(body) > 200_000:
            raise BizError("文档内容不能超过 200000 字")
        doc_title = (title or "").strip() or f"runtime-{int(__import__('time').time() * 1000)}"
        if len(doc_title) > 255:
            raise BizError("文档标题不能超过 255 字")
        document = session.scalar(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.knowledge_base_id == base_id,
                KnowledgeDocument.title == doc_title,
                KnowledgeDocument.deleted == 0,
            )
            .limit(1)
        )
        if document is None:
            document = KnowledgeDocument(
                knowledge_base_id=base_id,
                title=doc_title,
                source_type="NODE",
                content=body,
                char_count=len(body),
                status="PENDING",
                chunk_count=0,
            )
            session.add(document)
            session.flush()
        else:
            document.content = body
            document.char_count = len(body)
            document.source_type = "NODE"
            for chunk in session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
            ).all():
                session.delete(chunk)
        return self._index(session, base_id, document.id)

    def delete_document(self, session: Session, base_id: int, document_id: int, user: CurrentUser | None) -> None:
        self._owned(session, base_id, user)
        document = self._require_document(session, base_id, document_id)
        for chunk in session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
        ).all():
            session.delete(chunk)
        session.delete(document)

    def preview(self, session: Session, base_id: int, document_id: int, chunk_size: Any,
                chunk_overlap: Any, user: CurrentUser | None) -> list[dict[str, Any]]:
        base = self._owned(session, base_id, user)
        document = self._require_document(session, base_id, document_id)
        size = _clamp(chunk_size, 200, 2000, base.chunk_size)
        overlap = _clamp(chunk_overlap, 0, size // 2, base.chunk_overlap)
        chunks = split(document.content, size, overlap)
        return [
            {"chunkIndex": index, "content": content, "charCount": len(content)}
            for index, content in enumerate(chunks)
        ]

    def index_document(self, session: Session, base_id: int, document_id: int,
                       user: CurrentUser | None) -> dict[str, Any]:
        self._owned(session, base_id, user)
        return self._index(session, base_id, document_id)

    def search(self, session: Session, base_id: int, query: str | None, top_k: Any,
               user: CurrentUser | None) -> list[dict[str, Any]]:
        return self._do_search(session, self._owned(session, base_id, user), query, top_k)

    def search_for_runtime(self, session: Session, base_id: int, query: str | None,
                           top_k: Any) -> list[dict[str, Any]]:
        return self._do_search(session, self._get(session, base_id), query, top_k)

    # ---------------------------------------------------------------- internals
    def _import_text(self, session: Session, base_id: int, title: str | None, content: str | None,
                     source_type: str | None) -> dict[str, Any]:
        if not content or not content.strip():
            raise BizError("文档内容不能为空")
        document = KnowledgeDocument(
            knowledge_base_id=base_id,
            title=(title or "").strip() or "未命名文档",
            source_type=source_type or "TEXT",
            content=content,
            char_count=len(content),
            status="PENDING",
            chunk_count=0,
        )
        session.add(document)
        session.flush()
        return self._doc_vo(document)

    def _index(self, session: Session, base_id: int, document_id: int) -> dict[str, Any]:
        base = self._get(session, base_id)
        document = self._require_document(session, base_id, document_id)
        chunks = split(document.content, base.chunk_size, base.chunk_overlap)
        if not chunks:
            document.status = "FAILED"
            document.error_message = "文档内容为空，无法分片"
            session.flush()
            return self._doc_vo(document)
        try:
            vectors: list[list[float]] = []
            model = base.embedding_model
            mock = False
            for start in range(0, len(chunks), EMBED_BATCH):
                batch_vectors, batch_model, batch_mock = self._embed(
                    session, base, chunks[start : start + EMBED_BATCH]
                )
                vectors.extend(batch_vectors)
                model = batch_model
                mock = batch_mock
            if len(vectors) != len(chunks):
                raise RuntimeError("embedding 返回数量与分片数量不一致")
            for chunk in session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
            ).all():
                session.delete(chunk)
            session.flush()
            for index, content in enumerate(chunks):
                session.add(
                    KnowledgeChunk(
                        knowledge_base_id=base_id,
                        document_id=document.id,
                        chunk_index=index,
                        content=content,
                        char_count=len(content),
                        embedding_model="mock-embedding" if mock else model,
                        embedding=None if mock else dumps(vectors[index]),
                    )
                )
            document.status = "INDEXED"
            document.chunk_count = len(chunks)
            document.error_message = None
            document.char_count = len(document.content)
            session.flush()
        except Exception as exc:  # noqa: BLE001
            document.status = "FAILED"
            message = str(exc) or "索引失败"
            document.error_message = message[:500]
            session.flush()
            log.warning("index document failed, docId=%s: %s", document_id, exc)
        return self._doc_vo(document)

    def _do_search(self, session: Session, base: KnowledgeBase, query: str | None,
                   top_k: Any) -> list[dict[str, Any]]:
        if not query or not query.strip():
            raise BizError("检索内容不能为空")
        limit = _clamp(top_k, 1, MAX_TOP_K, 4)
        chunks = session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == base.id)
        ).all()
        if not chunks:
            return []
        titles = {
            item.id: item.title
            for item in session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.deleted == 0
                )
            ).all()
        }
        try:
            vectors, _model, mock = self._embed(session, base, [query.strip()])
        except Exception as exc:  # noqa: BLE001
            log.warning("query embedding failed, fallback to lexical: %s", exc)
            vectors, mock = [], True

        lexical = mock or not vectors
        query_vector = None if lexical else vectors[0]
        query_grams = gram_counts(query)
        gram_list = [gram_counts(item.content) for item in chunks]
        frequencies = document_frequency(query_grams, gram_list)
        ceiling = lexical_ceiling(query_grams, len(chunks), frequencies)

        hits: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            lexical_score_value = lexical_score(query_grams, gram_list[index], len(chunks), frequencies, ceiling)
            score = lexical_score_value
            if not lexical and query_vector is not None:
                stored = loads(chunk.embedding)
                if isinstance(stored, list) and len(stored) == len(query_vector):
                    score = hybrid(cosine(query_vector, [float(v) for v in stored]), lexical_score_value)
            hits.append(
                {
                    "chunkId": chunk.id,
                    "documentId": chunk.document_id,
                    "title": titles.get(chunk.document_id, ""),
                    "content": chunk.content,
                    "score": round(score * 1000) / 1000,
                }
            )
        hits = [hit for hit in hits if hit["score"] > 0]
        hits.sort(key=lambda hit: hit["score"], reverse=True)
        return hits[:limit]

    def _embed(self, session: Session, base: KnowledgeBase, texts: list[str]) -> tuple[list[list[float]], str, bool]:
        payload: dict[str, Any] = {
            "provider": base.embedding_provider,
            "model": base.embedding_model,
            "input": texts,
        }
        credentials = self.providers.credentials(session, base.embedding_provider)
        if credentials is not None:
            payload["apiKey"] = credentials.get("apiKey", "")
            payload["baseUrl"] = credentials.get("baseUrl", "")
        data = (self.ai.post_json("/v1/embeddings", payload) or {}).get("data") or {}
        vectors = [[float(value) for value in vector] for vector in (data.get("vectors") or [])]
        return vectors, str(data.get("model") or base.embedding_model), bool(data.get("mock"))

    def _owned(self, session: Session, base_id: int, user: CurrentUser | None) -> KnowledgeBase:
        base = self._get(session, base_id)
        if user is not None and not user.is_admin and base.user_id != user.id:
            raise not_found(f"知识库不存在: {base_id}")
        return base

    @staticmethod
    def _get(session: Session, base_id: int) -> KnowledgeBase:
        base = session.scalar(
            select(KnowledgeBase).where(KnowledgeBase.id == base_id, KnowledgeBase.deleted == 0)
        )
        if base is None:
            raise not_found(f"知识库不存在: {base_id}")
        return base

    @staticmethod
    def _require_document(session: Session, base_id: int, document_id: int) -> KnowledgeDocument:
        document = session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id, KnowledgeDocument.deleted == 0
            )
        )
        if document is None or document.knowledge_base_id != base_id:
            raise not_found(f"文档不存在: {document_id}")
        return document

    @staticmethod
    def _doc_vo(document: KnowledgeDocument) -> dict[str, Any]:
        return {
            "id": document.id,
            "title": document.title,
            "sourceType": document.source_type,
            "charCount": document.char_count,
            "status": document.status,
            "chunkCount": document.chunk_count,
            "errorMessage": document.error_message,
            "createdAt": iso(document.created_at),
        }

    @staticmethod
    def _to_vo(session: Session, base: KnowledgeBase) -> dict[str, Any]:
        documents = session.scalar(
            select(func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.deleted == 0)
        ) or 0
        chunks = session.scalar(
            select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.knowledge_base_id == base.id)
        ) or 0
        return {
            "id": base.id,
            "name": base.name,
            "description": base.description,
            "embeddingProvider": base.embedding_provider,
            "embeddingModel": base.embedding_model,
            "chunkSize": base.chunk_size,
            "chunkOverlap": base.chunk_overlap,
            "documentCount": int(documents),
            "chunkCount": int(chunks),
            "createdAt": iso(base.created_at),
        }
