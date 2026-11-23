from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.database import session_scope
from app.http import current_user
from app.serialization import ok
from app.services.memory import MemoryService

router = APIRouter(prefix="/api/memories", tags=["memories"])
service = MemoryService()


@router.get("")
def list_memories(request: Request, scope: str | None = Query(default=None),
                  workflowId: int | None = Query(default=None)):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.list_memories(session, user, scope, workflowId))


@router.delete("/{memory_id}")
def delete_memory(memory_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        service.delete(session, memory_id, user)
        return ok()
