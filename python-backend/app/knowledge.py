from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import agent_plan
from .agent_plan import DEFAULT_EMBEDDING_MODEL, cosine
from .db import first_text, format_dt, jdump, jload, now, text_or_none, to_float, to_int
from .models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, KnowledgeIndexTask

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100
STOP_TERMS = {
    "应该", "怎么", "什么", "如何", "可以", "需要", "一个", "这个", "那个", "是否", "以及",
    "the", "and", "for", "with", "what", "how",
}


def _normalize_chunk_size(value: Any, fallback: Optional[int] = None) -> int:
    default = DEFAULT_CHUNK_SIZE if fallback is None else fallback
    size = to_int(value, default) or default
    return max(100, min(4000, size))


def _normalize_chunk_overlap(value: Any, chunk_size: int, fallback: Optional[int] = None) -> int:
    default = DEFAULT_CHUNK_OVERLAP if fallback is None else fallback
    overlap = to_int(value, default) or 0
    return max(0, min(max(0, chunk_size - 1), overlap))


def split_content(content: Optional[str], chunk_size: Any, overlap: Any) -> list[str]:
    if not content or not content.strip():
        return []
    size = _normalize_chunk_size(chunk_size)
    safe_overlap = _normalize_chunk_overlap(overlap, size)
    step = max(1, size - safe_overlap)
    text = content.strip()
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        result.append(text[start:end])
        if end >= len(text):
            break
        start += step
    return result


def base_to_dict(base: KnowledgeBase) -> dict:
    return {
        "id": base.id,
        "name": base.name,
        "description": base.description,
        "configId": base.config_id,
        "embeddingModel": base.embedding_model,
        "chunkSize": base.chunk_size,
        "chunkOverlap": base.chunk_overlap,
        "status": base.status,
        "documentCount": base.document_count,
        "chunkCount": base.chunk_count,
        "charCount": base.char_count,
        "createdAt": format_dt(base.created_at),
        "updatedAt": format_dt(base.updated_at),
    }


def document_to_dict(document: KnowledgeDocument) -> dict:
    return {
        "id": document.id,
        "knowledgeBaseId": document.knowledge_base_id,
        "title": document.title,
        "sourceType": document.source_type,
        "sourceUrl": document.source_url,
        "fileName": document.file_name,
        "tags": document.tags,
        "status": document.status,
        "charCount": document.char_count,
        "errorMessage": document.error_message,
        "createdAt": format_dt(document.created_at),
        "updatedAt": format_dt(document.updated_at),
    }


def task_to_dict(task: KnowledgeIndexTask) -> dict:
    return {
        "id": task.id,
        "knowledgeBaseId": task.knowledge_base_id,
        "documentId": task.document_id,
        "status": task.status,
        "progress": task.progress,
        "totalChunks": task.total_chunks,
        "finishedChunks": task.finished_chunks,
        "errorMessage": task.error_message,
        "createdAt": format_dt(task.created_at),
        "updatedAt": format_dt(task.updated_at),
    }


def _require_base(db: Session, base_id: int) -> KnowledgeBase:
    base = db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == base_id, KnowledgeBase.deleted == 0)
    ).scalar_one_or_none()
    if base is None:
        raise ValueError("知识库不存在")
    return base


def _require_document(db: Session, base_id: int, document_id: int) -> KnowledgeDocument:
    document = db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.deleted == 0
        )
    ).scalar_one_or_none()
    if document is None or document.knowledge_base_id != base_id:
        raise ValueError("知识文档不存在")
    return document


def list_knowledge_bases(db: Session) -> list[dict]:
    rows = db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.deleted == 0)
        .order_by(KnowledgeBase.updated_at.desc())
    ).scalars()
    return [base_to_dict(row) for row in rows]


def list_documents(db: Session, base_id: int) -> list[dict]:
    rows = db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.deleted == 0)
        .order_by(KnowledgeDocument.updated_at.desc())
    ).scalars()
    return [document_to_dict(row) for row in rows]


def get_knowledge_base(db: Session, base_id: int) -> dict:
    base = _require_base(db, base_id)
    output = base_to_dict(base)
    output["documents"] = list_documents(db, base_id)
    tasks = db.execute(
        select(KnowledgeIndexTask)
        .where(KnowledgeIndexTask.knowledge_base_id == base_id, KnowledgeIndexTask.deleted == 0)
        .order_by(KnowledgeIndexTask.updated_at.desc())
        .limit(10)
    ).scalars()
    output["recentTasks"] = [task_to_dict(task) for task in tasks]
    return output


def delete_knowledge_base(db: Session, base_id: int) -> None:
    _require_base(db, base_id)
    db.execute(
        update(KnowledgeChunk)
        .where(KnowledgeChunk.knowledge_base_id == base_id, KnowledgeChunk.deleted == 0)
        .values(deleted=1)
    )
    db.execute(
        update(KnowledgeIndexTask)
        .where(KnowledgeIndexTask.knowledge_base_id == base_id, KnowledgeIndexTask.deleted == 0)
        .values(deleted=1)
    )
    db.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.deleted == 0)
        .values(deleted=1)
    )
    db.execute(
        update(KnowledgeBase).where(KnowledgeBase.id == base_id).values(deleted=1, updated_at=now())
    )
    db.commit()


def create_knowledge_base(db: Session, payload: dict) -> dict:
    name = text_or_none(payload.get("name"))
    if not name:
        raise ValueError("知识库名称不能为空")
    base = KnowledgeBase()
    base.name = name
    base.description = text_or_none(payload.get("description"))
    base.config_id = to_int(payload.get("configId"))
    base.embedding_model = first_text(payload.get("embeddingModel"), DEFAULT_EMBEDDING_MODEL)
    base.chunk_size = _normalize_chunk_size(payload.get("chunkSize"))
    base.chunk_overlap = _normalize_chunk_overlap(payload.get("chunkOverlap"), base.chunk_size)
    base.status = "DRAFT"
    base.document_count = 0
    base.chunk_count = 0
    base.char_count = 0
    base.deleted = 0
    db.add(base)
    db.commit()
    db.refresh(base)
    return base_to_dict(base)


def import_text(db: Session, base_id: int, payload: dict) -> dict:
    base = _require_base(db, base_id)
    content = payload.get("content")
    if content is None or not str(content).strip():
        raise ValueError("导入文本不能为空")
    content = str(content)
    document = KnowledgeDocument()
    document.knowledge_base_id = base.id
    document.title = first_text(payload.get("title"), "未命名文本")
    document.source_type = "TEXT"
    document.raw_text = content
    document.tags = _to_tags_json(text_or_none(payload.get("tags"))) if text_or_none(payload.get("tags")) else None
    document.status = "IMPORTED"
    document.char_count = len(content)
    document.deleted = 0
    db.add(document)
    db.commit()
    db.refresh(document)
    refresh_base_stats(db, base.id, "IMPORTED")
    return document_to_dict(document)


def upload_text_file(db: Session, base_id: int, file_name: str, data: bytes) -> dict:
    if not data:
        raise ValueError("上传文件不能为空")
    file_name = first_text(file_name, "uploaded.txt") or "uploaded.txt"
    if not is_text_file(file_name):
        raise ValueError("当前版本仅支持 txt、md、markdown 文本文件")
    content = data.decode("utf-8", errors="replace")
    output = import_text(db, base_id, {"title": file_name, "content": content})
    document = _require_document(db, base_id, int(output["id"]))
    document.file_name = file_name
    db.commit()
    db.refresh(document)
    return document_to_dict(document)


def preview_chunks(db: Session, base_id: int, document_id: int, payload: Optional[dict]) -> list[dict]:
    base = _require_base(db, base_id)
    document = _require_document(db, base_id, document_id)
    payload = payload or {}
    chunk_size = _normalize_chunk_size(payload.get("chunkSize"), base.chunk_size)
    overlap = _normalize_chunk_overlap(payload.get("chunkOverlap"), chunk_size, base.chunk_overlap)
    chunks = split_content(document.raw_text, chunk_size, overlap)
    return [
        {"chunkIndex": index, "content": chunk, "charCount": len(chunk)}
        for index, chunk in enumerate(chunks)
    ]


def _create_task(db: Session, base_id: int, document_id: int) -> KnowledgeIndexTask:
    task = KnowledgeIndexTask()
    task.knowledge_base_id = base_id
    task.document_id = document_id
    task.status = "RUNNING"
    task.progress = 0
    task.total_chunks = 0
    task.finished_chunks = 0
    task.deleted = 0
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _mark_old_chunks_deleted(db: Session, base_id: int, document_id: int) -> None:
    db.execute(
        update(KnowledgeChunk)
        .where(
            KnowledgeChunk.knowledge_base_id == base_id,
            KnowledgeChunk.document_id == document_id,
            KnowledgeChunk.deleted == 0,
        )
        .values(deleted=1)
    )
    db.commit()


def index_document(db: Session, base_id: int, document_id: int) -> dict:
    base = _require_base(db, base_id)
    document = _require_document(db, base_id, document_id)
    task = _create_task(db, base.id, document.id)
    try:
        chunks = split_content(document.raw_text, base.chunk_size, base.chunk_overlap)
        _mark_old_chunks_deleted(db, base.id, document.id)

        config = agent_plan.resolve_knowledge_config(db, base.config_id, base.embedding_model)
        can_embed = bool(config.api_url and config.api_key and config.model)
        for index, chunk_text in enumerate(chunks):
            embedding = agent_plan.agent_plan_client.create_embedding(config, chunk_text) if can_embed else []
            chunk = KnowledgeChunk()
            chunk.knowledge_base_id = base.id
            chunk.document_id = document.id
            chunk.chunk_index = index
            chunk.title = document.title
            chunk.content = chunk_text
            chunk.source_url = document.source_url
            chunk.tags = _to_tags_json(document.tags)
            chunk.embedding_model = config.model
            chunk.embedding = jdump(embedding)
            chunk.status = "READY"
            chunk.char_count = len(chunk_text)
            chunk.deleted = 0
            db.add(chunk)
            db.flush()

            task.finished_chunks = index + 1
            task.total_chunks = len(chunks)
            task.progress = 100 if not chunks else round(((index + 1) * 100.0) / len(chunks))
        db.commit()

        document.status = "READY"
        document.error_message = None
        task.status = "SUCCESS"
        task.progress = 100
        db.commit()
        refresh_base_stats(db, base.id, "READY")
    except Exception as exc:
        db.rollback()
        document = _require_document(db, base.id, document_id)
        document.status = "FAILED"
        document.error_message = str(exc)
        task = db.execute(
            select(KnowledgeIndexTask).where(KnowledgeIndexTask.id == task.id)
        ).scalar_one()
        task.status = "FAILED"
        task.error_message = str(exc)
        db.commit()
        refresh_base_stats(db, base.id, "FAILED")
    db.refresh(task)
    return task_to_dict(task)


def _query_embedding(db: Session, base: KnowledgeBase, query: str) -> list[float]:
    try:
        config = agent_plan.resolve_knowledge_config(db, base.config_id, base.embedding_model)
        if config.api_url and config.api_key and config.model:
            return agent_plan.agent_plan_client.create_embedding(config, query)
    except Exception:
        return []
    return []


def search(db: Session, base_id: int, payload: dict) -> dict:
    base = _require_base(db, base_id)
    query = payload.get("query")
    if not query:
        raise ValueError("检索问题不能为空")
    embedding = _query_embedding(db, base, str(query))
    top_k = to_int(payload.get("topK"), 5) or 5
    threshold = to_float(payload.get("scoreThreshold"), 0.2)
    if threshold is None:
        threshold = 0.2
    return retrieve(db, str(base.id), str(query), embedding, top_k, threshold)


def search_runtime(db: Session, knowledge_base_id: Optional[str], query: str, top_k: int, score_threshold: float) -> dict:
    base_id = _resolve_base_id(db, knowledge_base_id)
    base = _require_base(db, base_id)
    embedding = _query_embedding(db, base, query)
    return retrieve(db, str(base.id), query, embedding, top_k, score_threshold)


def retrieve(
    db: Session,
    knowledge_base_id: str,
    query: str,
    query_embedding: Optional[list[float]],
    top_k: int,
    score_threshold: float,
) -> dict:
    base_id = _resolve_base_id(db, knowledge_base_id)
    effective_threshold = 0.000001 if score_threshold <= 0 else score_threshold
    rows = db.execute(
        select(KnowledgeChunk).where(
            KnowledgeChunk.knowledge_base_id == base_id,
            KnowledgeChunk.status == "READY",
            KnowledgeChunk.deleted == 0,
        )
    ).scalars()
    matches: list[dict] = []
    for chunk in rows:
        vector_score = cosine(query_embedding, _parse_embedding(chunk.embedding))
        text_score = _text_relevance(query, chunk.content)
        score = max(vector_score, text_score)
        if score < effective_threshold:
            continue
        matches.append(
            {
                "chunkId": chunk.id,
                "knowledgeBaseId": chunk.knowledge_base_id,
                "documentId": chunk.document_id,
                "title": chunk.title,
                "content": chunk.content,
                "sourceUrl": chunk.source_url,
                "tags": chunk.tags,
                "score": score,
            }
        )
    matches.sort(key=lambda item: item["score"], reverse=True)
    matches = matches[: max(1, top_k)]
    context = "\n".join(f"- {item['content']}" for item in matches)
    return {
        "chunks": matches,
        "citations": [item["chunkId"] for item in matches],
        "context": context,
    }


def upsert(
    db: Session,
    knowledge_base_id: str,
    title: Optional[str],
    content: str,
    source_url: Optional[str],
    tags: Optional[list[str]],
    embedding: Optional[list[float]],
    embedding_model: Optional[str],
) -> dict:
    base = _resolve_base_for_runtime(db, knowledge_base_id, embedding_model)
    document_map = import_text(
        db,
        base.id,
        {
            "title": first_text(title, "工作流写入"),
            "content": content,
            "tags": ",".join(tags) if tags else None,
        },
    )
    document = _require_document(db, base.id, int(document_map["id"]))
    chunks = split_content(content, base.chunk_size, base.chunk_overlap)
    _mark_old_chunks_deleted(db, base.id, document.id)
    for index, chunk_text in enumerate(chunks):
        chunk = KnowledgeChunk()
        chunk.knowledge_base_id = base.id
        chunk.document_id = document.id
        chunk.chunk_index = index
        chunk.title = document.title
        chunk.content = chunk_text
        chunk.source_url = source_url
        chunk.tags = _to_tags_json(document.tags)
        chunk.embedding_model = embedding_model
        chunk.embedding = jdump(embedding if index == 0 and embedding else [])
        chunk.status = "READY"
        chunk.char_count = len(chunk_text)
        chunk.deleted = 0
        db.add(chunk)
    document.status = "READY"
    document.source_url = source_url
    db.commit()
    refresh_base_stats(db, base.id, "READY")
    return {
        "knowledgeBaseId": base.id,
        "contentId": document.id,
        "chunkCount": len(chunks),
        "indexed": True,
    }


def _resolve_base_for_runtime(db: Session, knowledge_base_id: Optional[str], embedding_model: Optional[str]) -> KnowledgeBase:
    if knowledge_base_id and str(knowledge_base_id).strip().lower() != "default":
        text = str(knowledge_base_id).strip()
        try:
            base_id = int(text)
        except (ValueError, TypeError):
            named = db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.name == text, KnowledgeBase.deleted == 0)
                .limit(1)
            ).scalar_one_or_none()
            if named is not None:
                return named
        else:
            return _require_base(db, base_id)
    existing = db.execute(
        select(KnowledgeBase)
        .where(KnowledgeBase.name == "默认知识库", KnowledgeBase.deleted == 0)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    created = create_knowledge_base(
        db,
        {
            "name": "默认知识库",
            "description": "工作流运行时自动写入的默认知识库",
            "embeddingModel": embedding_model,
        },
    )
    return _require_base(db, int(created["id"]))


def _resolve_base_id(db: Session, knowledge_base_id: Optional[str]) -> int:
    return _resolve_base_for_runtime(db, knowledge_base_id, None).id


def refresh_base_stats(db: Session, base_id: int, status: str) -> None:
    base = _require_base(db, base_id)
    document_count = db.execute(
        select(func.count()).select_from(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.deleted == 0
        )
    ).scalar_one()
    chunk_count = db.execute(
        select(func.count()).select_from(KnowledgeChunk).where(
            KnowledgeChunk.knowledge_base_id == base_id,
            KnowledgeChunk.status == "READY",
            KnowledgeChunk.deleted == 0,
        )
    ).scalar_one()
    documents = db.execute(
        select(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_base_id == base_id, KnowledgeDocument.deleted == 0
        )
    ).scalars()
    char_count = sum(int(document.char_count or 0) for document in documents)
    base.document_count = int(document_count)
    base.chunk_count = int(chunk_count)
    base.char_count = char_count
    base.status = status
    db.commit()


def _parse_embedding(raw: Optional[str]) -> list[float]:
    value = jload(raw, [])
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float))]


def _normalize_search_text(text: Optional[str]) -> str:
    if not text:
        return ""
    lowered = text.lower()
    cleaned = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", cleaned).strip()


def _search_terms(normalized_query: str) -> set[str]:
    terms: set[str] = set()
    for part in normalized_query.split():
        if not part:
            continue
        if re.search(r"[\u4e00-\u9fff]", part):
            if len(part) <= 4 and part not in STOP_TERMS:
                terms.add(part)
            else:
                for size in (2, 3, 4):
                    if len(part) < size:
                        continue
                    for index in range(len(part) - size + 1):
                        term = part[index : index + size]
                        if term not in STOP_TERMS:
                            terms.add(term)
        elif len(part) >= 2 and part not in STOP_TERMS:
            terms.add(part)
    return terms


def _text_relevance(query: Optional[str], content: Optional[str]) -> float:
    normalized_query = _normalize_search_text(query)
    normalized_content = _normalize_search_text(content)
    if not normalized_query or not normalized_content:
        return 0.0
    if normalized_query in normalized_content:
        return 1.0
    terms = _search_terms(normalized_query)
    if not terms:
        return 0.0
    total_weight = 0.0
    matched_weight = 0.0
    for term in terms:
        weight = min(4, max(1, len(term) - 1))
        total_weight += weight
        if term in normalized_content:
            matched_weight += weight
    if total_weight == 0 or matched_weight == 0:
        return 0.0
    return min(0.95, matched_weight / total_weight)


def _to_tags_json(tags_text: Optional[str]) -> str:
    if not tags_text:
        return jdump([])
    parsed = jload(tags_text, None)
    if isinstance(parsed, list):
        return jdump([str(item) for item in parsed if str(item).strip()])
    return jdump([part.strip() for part in re.split(r"[,，\s]+", tags_text) if part.strip()])


def is_text_file(file_name: str) -> bool:
    lowered = file_name.lower()
    return lowered.endswith(".txt") or lowered.endswith(".md") or lowered.endswith(".markdown")
