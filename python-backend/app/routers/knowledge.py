from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import knowledge
from ..db import get_db
from ..result import error, success

router = APIRouter(prefix="/api/knowledge-bases", tags=["知识库管理接口"])


@router.get("")
def list_knowledge_bases(db: Session = Depends(get_db)):
    return success(knowledge.list_knowledge_bases(db))


@router.post("")
def create_knowledge_base(payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        return success(knowledge.create_knowledge_base(db, payload or {}))
    except ValueError as exc:
        if "名称" in str(exc):
            return JSONResponse(status_code=400, content=error(str(exc), 400))
        return error(str(exc))


@router.get("/{base_id}")
def get_knowledge_base(base_id: int, db: Session = Depends(get_db)):
    try:
        return success(knowledge.get_knowledge_base(db, base_id))
    except Exception as exc:
        return error(str(exc))


@router.delete("/{base_id}")
def delete_knowledge_base(base_id: int, db: Session = Depends(get_db)):
    try:
        knowledge.delete_knowledge_base(db, base_id)
        return success()
    except Exception as exc:
        return error(str(exc))


@router.post("/{base_id}/documents/text")
def import_text(base_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    try:
        return success(knowledge.import_text(db, base_id, payload))
    except ValueError as exc:
        if "文本不能为空" in str(exc):
            return JSONResponse(status_code=400, content=error(str(exc), 400))
        return error(str(exc))


@router.post("/{base_id}/documents/upload")
async def upload_text(base_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        data = await file.read()
        return success(knowledge.upload_text_file(db, base_id, file.filename or "", data))
    except ValueError as exc:
        return error(str(exc))
    except Exception as exc:
        return error(str(exc))


@router.get("/{base_id}/documents")
def list_documents(base_id: int, db: Session = Depends(get_db)):
    return success(knowledge.list_documents(db, base_id))


@router.post("/{base_id}/documents/{document_id}/preview-chunks")
def preview_chunks(base_id: int, document_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        return success(knowledge.preview_chunks(db, base_id, document_id, payload))
    except Exception as exc:
        return error(str(exc))


@router.post("/{base_id}/documents/{document_id}/index")
def index_document(base_id: int, document_id: int, db: Session = Depends(get_db)):
    try:
        return success(knowledge.index_document(db, base_id, document_id))
    except Exception as exc:
        return error(str(exc))


@router.post("/{base_id}/search")
def search(base_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    try:
        return success(knowledge.search(db, base_id, payload))
    except ValueError as exc:
        if "不能为空" in str(exc):
            return JSONResponse(status_code=400, content=error(str(exc), 400))
        return error(str(exc))
    except Exception as exc:
        return error(str(exc))
