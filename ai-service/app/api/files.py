"""Internal, user-scoped file upload / download / listing API.

All routes, including /files/{name}, require the platform internal token and storage context.

The platform service proxies these endpoints through ``/api/files`` so browsers and
external callers only need to talk to the platform port.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.internal_auth import require_internal
from app.config import Settings, get_settings
from app.core.storage import (
    FileNotFoundStorageError,
    StorageError,
    delete_file,
    file_metadata,
    legacy_storage,
    list_files,
    read_text,
    resolve_existing,
    save_text,
    save_upload,
    user_storage,
)

router = APIRouter(tags=["files"])


def file_settings(x_internal_token: str = Header(default=""), x_storage_user_id: int | None = Header(default=None),
                  x_storage_legacy: bool = Header(default=False)) -> Settings:
    require_internal(x_internal_token)
    try:
        return legacy_storage(get_settings()) if x_storage_legacy else user_storage(get_settings(), x_storage_user_id)
    except StorageError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


FileSettings = Annotated[Settings, Depends(file_settings)]


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
async def list_files_api(settings: FileSettings, prefix: str = "", limit: int = Query(default=500, ge=1, le=5000)):
    try:
        return {"data": list_files(settings, prefix=prefix, limit=limit)}
    except StorageError as exc:
        _raise_http(exc)


@router.post("/v1/files")
async def upload_raw(request: Request, settings: FileSettings, name: str = "") -> dict[str, Any]:
    """Raw-body upload used by the platform service and simple HTTP clients.

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
                    settings,
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
            settings,
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
    file: Annotated[UploadFile, File()],
    settings: FileSettings,
    name: str = Form(default=""),
    overwrite: bool = Form(default=False),
) -> dict[str, Any]:
    data = await file.read()
    _check_size(len(data))
    if not data:
        raise HTTPException(status_code=400, detail="上传内容为空")
    try:
        metadata = save_upload(
            settings,
            data,
            original_name=file.filename,
            name=name,
            overwrite=overwrite,
        )
    except StorageError as exc:
        _raise_http(exc)
    return {"data": metadata}


@router.post("/v1/files/text")
async def write_text(request: TextFileRequest, settings: FileSettings) -> dict[str, Any]:
    _check_size(len(request.content.encode(request.encoding)))
    try:
        metadata = save_text(
            settings,
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
async def file_meta(name: str, settings: FileSettings):
    try:
        path, rel = resolve_existing(settings, name)
    except StorageError as exc:
        _raise_http(exc)
    return {"data": file_metadata(path, rel, settings=settings)}


@router.get("/v1/files/{name:path}/text")
async def read_text_api(
    name: str,
    settings: FileSettings,
    encoding: str = "utf-8",
    max_chars: int = Query(default=0, ge=0, le=5_000_000),
):
    limit = max_chars or settings.max_read_chars
    try:
        return {"data": read_text(settings, name, encoding=encoding, max_chars=limit)}
    except StorageError as exc:
        _raise_http(exc)


@router.get("/v1/files/{name:path}")
async def download_v1(name: str, settings: FileSettings, download: bool = False):
    return _serve(name, download, settings)


@router.delete("/v1/files/{name:path}")
async def remove_file(name: str, settings: FileSettings):
    try:
        return {"data": delete_file(settings, name)}
    except StorageError as exc:
        _raise_http(exc)


@router.get("/files/{name:path}")
async def download_file(name: str, settings: FileSettings, download: bool = False):
    return _serve(name, download, settings)


def _serve(name: str, download: bool, settings: Settings) -> FileResponse:
    try:
        path, rel = resolve_existing(settings, name)
    except StorageError as exc:
        _raise_http(exc)
    metadata = file_metadata(path, rel, settings=settings)
    active = path.suffix.lower() in {".html", ".htm", ".svg", ".xml", ".xhtml"}
    return FileResponse(
        path,
        media_type="application/octet-stream" if active else metadata["contentType"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "sandbox; default-src 'none'"},
        filename=metadata["fileName"] if download or active else None,
    )
