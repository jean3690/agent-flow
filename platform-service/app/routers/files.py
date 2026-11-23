from __future__ import annotations

import asyncio
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import Response

from app.errors import BizError
from app.http import current_user
from app.serialization import ok
from app.services.files import FileService, media_type

router = APIRouter(prefix="/api/files", tags=["files"])
service = FileService()

ACTIVE_EXTENSIONS = (".html", ".htm", ".svg", ".xml", ".xhtml", ".js", ".mjs")


@router.get("")
def list_files(request: Request, prefix: str = Query(default=""), limit: int = Query(default=500),
               ownerUserId: int | None = Query(default=None), legacy: bool = Query(default=False)):
    user = current_user(request)
    return ok(service.list_files(prefix, limit, ownerUserId, legacy, user))


@router.post("")
@router.post("/upload")
async def upload_file(
    request: Request, file: Annotated[UploadFile, File()], name: str | None = Query(default=None)
):
    user = current_user(request)
    content = await file.read()
    if not content:
        raise BizError("上传文件为空")
    target = (name or "").strip()
    if not target:
        original = (file.filename or "upload.bin").replace("\\", "/")
        target = original.rsplit("/", 1)[-1] or "upload.bin"
    content_type = file.content_type

    def run():
        return service.upload(target, content, content_type, user)

    return ok(await asyncio.to_thread(run))


@router.post("/text")
def write_text(request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    if not str(payload.get("name") or "").strip():
        raise BizError("文件路径不能为空")
    return ok(service.write_text(payload, user))


@router.delete("/{name:path}")
def delete_file(name: str, request: Request):
    user = current_user(request)
    return ok(service.delete(name, user))


@router.get("/{name:path}")
def download_file(name: str, request: Request, download: bool = Query(default=False)):
    user = current_user(request)
    result = service.download(name, user)
    lower = result.name.lower()
    active = lower.endswith(ACTIVE_EXTENSIONS)
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    if download or active:
        headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(result.name, safe="")
    return Response(
        content=result.content,
        media_type="application/octet-stream" if active else media_type(result.name),
        headers=headers,
    )
