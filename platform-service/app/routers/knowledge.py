from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Request, UploadFile

from app.database import session_scope
from app.http import current_user, require_text
from app.serialization import ok
from app.services.knowledge import KnowledgeService

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge"])
service = KnowledgeService()


@router.get("")
def list_bases(request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.list_bases(session, user))


@router.post("")
def create_base(request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    require_text(payload, "name", "知识库名称不能为空", 128)
    with session_scope() as session:
        return ok(service.create(session, payload, user))


@router.get("/{base_id}")
def detail_base(base_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.detail(session, base_id, user))


@router.delete("/{base_id}")
def delete_base(base_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        service.delete(session, base_id, user)
        return ok()


@router.get("/{base_id}/documents")
def list_documents(base_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.documents(session, base_id, user))


@router.post("/{base_id}/documents/text")
def import_text(base_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    with session_scope() as session:
        return ok(
            service.import_text(session, base_id, payload.get("title"), payload.get("content"), "TEXT", user)
        )


@router.post("/{base_id}/documents/upload")
async def upload_document(
    base_id: int, request: Request, file: Annotated[UploadFile, File()]
):
    user = current_user(request)
    content = await file.read()
    filename = file.filename

    def run():
        with session_scope() as session:
            return service.upload_text_file(session, base_id, filename, content, user)

    return ok(await asyncio.to_thread(run))


@router.delete("/{base_id}/documents/{document_id}")
def delete_document(base_id: int, document_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        service.delete_document(session, base_id, document_id, user)
        return ok()


@router.post("/{base_id}/documents/{document_id}/preview")
def preview(base_id: int, document_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    with session_scope() as session:
        return ok(
            service.preview(
                session, base_id, document_id, payload.get("chunkSize"), payload.get("chunkOverlap"), user
            )
        )


@router.post("/{base_id}/documents/{document_id}/index")
def index_document(base_id: int, document_id: int, request: Request):
    user = current_user(request)
    with session_scope() as session:
        return ok(service.index_document(session, base_id, document_id, user))


@router.post("/{base_id}/search")
def search(base_id: int, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    query = require_text(payload, "query", "检索内容不能为空")
    with session_scope() as session:
        return ok(service.search(session, base_id, query, payload.get("topK"), user))
