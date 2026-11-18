"""File upload / download / listing API.

Public download route:  GET /files/{name}
REST management routes: /v1/files*

The Java service proxies these endpoints through ``/api/files`` so browsers and
external callers only need to talk to the Java port.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.storage import (
    FileNotFoundStorageError,
    StorageError,
    delete_file,
    file_metadata,
    list_files,
    read_text,
    resolve_existing,
    save_text,
    save_upload,
)

router = APIRouter(tags=["files"])


class TextFileRequest(BaseModel):
    name: str = Field(min_length=1, description="存储目录内的相对路径，例如 reports/today.md")
    content: str = ""
    encoding: str = "utf-8"
    overwrite: bool = True
    append: bool = False


def _raise_http(exc: StorageError) -> None:
    status = 404 if isinstance(exc, FileNotFoundStorageError) else 400
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _check_size(size: int) -> None:
    settings = get_settings()
    limit = max(1, settings.max_upload_mb) * 1024 * 1024
    if size > limit:
        raise HTTPException(status_code=413, detail=f"文件超过大小上限 {settings.max_upload_mb}MB")


@router.get("/v1/files")
async def list_files_api(prefix: str = "", limit: int = Query(default=500, ge=1, le=5000)):
    settings = get_settings()
    return {"data": list_files(settings, prefix=prefix, limit=limit)}


@router.post("/v1/files")
async def upload_raw(request: Request, name: str = "") -> dict[str, Any]:
    """Raw-body upload used by the Java service and simple HTTP clients.

    ``name`` may be a query parameter or the ``X-File-Name`` header.  When the
    body is JSON with ``{name, content}`` it is treated as a text write, which
    makes the endpoint convenient for scripts.
    """

    body = await request.body()
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type and not name:
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and payload.get("content") is not None:
            request_model = TextFileRequest.model_validate(payload)
            _check_size(len(request_model.content.encode(request_model.encoding)))
            try:
                metadata = save_text(
                    get_settings(),
                    request_model.content,
                    name=request_model.name,
                    encoding=request_model.encoding,
                    overwrite=request_model.overwrite,
                    append=request_model.append,
                )
            except StorageError as exc:
                _raise_http(exc)
            return {"data": metadata}

    _check_size(len(body))
    if not body:
        raise HTTPException(status_code=400, detail="上传内容为空")
    filename = name or request.headers.get("x-file-name") or ""
    try:
        metadata = save_upload(
            get_settings(),
            body,
            original_name=filename or None,
            name=name,
            overwrite=False,
        )
    except StorageError as exc:
        _raise_http(exc)
    return {"data": metadata}


@router.post("/v1/files/upload")
async def upload_multipart(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    overwrite: bool = Form(default=False),
) -> dict[str, Any]:
    data = await file.read()
    _check_size(len(data))
    if not data:
        raise HTTPException(status_code=400, detail="上传内容为空")
    try:
        metadata = save_upload(
            get_settings(),
            data,
            original_name=file.filename,
            name=name,
            overwrite=overwrite,
        )
    except StorageError as exc:
        _raise_http(exc)
    return {"data": metadata}


@router.post("/v1/files/text")
async def write_text(request: TextFileRequest) -> dict[str, Any]:
    _check_size(len(request.content.encode(request.encoding)))
    try:
        metadata = save_text(
            get_settings(),
            request.content,
            name=request.name,
            encoding=request.encoding,
            overwrite=request.overwrite,
            append=request.append,
        )
    except StorageError as exc:
        _raise_http(exc)
    return {"data": metadata}


@router.get("/v1/files/{name:path}/meta")
async def file_meta(name: str):
    try:
        path, rel = resolve_existing(get_settings(), name)
    except StorageError as exc:
        _raise_http(exc)
    return {"data": file_metadata(path, rel)}


@router.get("/v1/files/{name:path}/text")
async def read_text_api(
    name: str,
    encoding: str = "utf-8",
    max_chars: int = Query(default=0, ge=0, le=5_000_000),
):
    settings = get_settings()
    limit = max_chars or settings.max_read_chars
    try:
        return {"data": read_text(settings, name, encoding=encoding, max_chars=limit)}
    except StorageError as exc:
        _raise_http(exc)


@router.get("/v1/files/{name:path}")
async def download_v1(name: str, download: bool = False):
    return _serve(name, download)


@router.delete("/v1/files/{name:path}")
async def remove_file(name: str):
    try:
        return {"data": delete_file(get_settings(), name)}
    except StorageError as exc:
        _raise_http(exc)


@router.get("/files/{name:path}")
async def download_public(name: str, download: bool = False):
    return _serve(name, download)


def _serve(name: str, download: bool) -> FileResponse:
    settings = get_settings()
    try:
        path, rel = resolve_existing(settings, name)
    except StorageError as exc:
        _raise_http(exc)
    metadata = file_metadata(path, rel)
    return FileResponse(
        path,
        media_type=metadata["contentType"],
        headers={"Cache-Control": "public, max-age=3600"},
        filename=metadata["fileName"] if download else None,
    )
