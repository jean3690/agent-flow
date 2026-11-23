from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, Request

from app.config import get_settings
from app.database import session_scope
from app.errors import BizError, unauthorized
from app.serialization import ok
from app.services.approvals import create as create_approval
from app.services.approvals import get as get_approval
from app.services.knowledge import KnowledgeService
from app.services.memory import MemoryService

router = APIRouter(prefix="/internal", tags=["internal"])
knowledge = KnowledgeService()
memory = MemoryService()


def _require(token: str | None) -> None:
    expected = get_settings().internal_token
    if not token or not hmac.compare_digest(token, expected):
        raise unauthorized("内部调用令牌无效")


@router.post("/approvals")
def create_approval_task(request: Request, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    payload = request.state.body or {}
    for field, label, limit in (("runId", "runId", 64), ("nodeId", "nodeId", 64), ("title", "title", 255)):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise BizError(f"{label} 不能为空")
        if len(value) > limit:
            raise BizError(f"{label} 不能超过 {limit} 字符")
    content = payload.get("content")
    if content is not None and len(str(content)) > 20_000:
        raise BizError("审批内容不能超过 20000 字")
    with session_scope() as session:
        return ok(
            create_approval(
                session,
                payload["runId"],
                payload.get("workflowId"),
                payload["nodeId"],
                payload.get("userId"),
                payload["title"],
                content,
                payload.get("expiresInSeconds"),
            )
        )


@router.get("/approvals/{task_id}")
def get_approval_task(task_id: int, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    with session_scope() as session:
        return ok(get_approval(session, task_id))


@router.post("/knowledge/search")
def search_knowledge(request: Request, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    payload = request.state.body or {}
    base_id = payload.get("knowledgeBaseId")
    if base_id is None:
        raise BizError("缺少知识库 ID")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise BizError("检索内容不能为空")
    with session_scope() as session:
        hits = knowledge.search_for_runtime(session, int(base_id), query, payload.get("topK"))
    return ok({"chunks": hits, "count": len(hits)})


@router.post("/knowledge/upsert")
def upsert_knowledge(request: Request, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    payload = request.state.body or {}
    base_id = payload.get("knowledgeBaseId")
    if base_id is None:
        raise BizError("缺少知识库 ID")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise BizError("文档内容不能为空")
    if len(content) > 200_000:
        raise BizError("文档内容不能超过 200000 字")
    with session_scope() as session:
        return ok(knowledge.upsert_for_runtime(session, int(base_id), payload.get("title"), content))


@router.post("/memory/write")
def write_memory(request: Request, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    with session_scope() as session:
        return ok(memory.write(session, request.state.body or {}))


@router.post("/memory/search")
def search_memory(request: Request, x_internal_token: str | None = Header(default=None)):
    _require(x_internal_token)
    with session_scope() as session:
        return ok(memory.search(session, request.state.body or {}))
