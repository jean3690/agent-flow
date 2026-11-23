from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile

from ..db import text_or_none
from ..minio_client import minio_service
from ..result import error, success

router = APIRouter(prefix="/api/media", tags=["媒体文件接口"])

MAX_IMAGE_SIZE = 10 * 1024 * 1024
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _extension_for(file_name: str, content_type: str) -> str:
    lower_name = file_name.lower()
    index = lower_name.rfind(".")
    if index >= 0 and index < len(lower_name) - 1:
        extension = lower_name[index:]
        if extension in IMAGE_EXTENSIONS:
            return extension
    mapping = {
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(content_type.lower(), ".png")


@router.post("/images")
async def upload_image(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        return error("上传图片不能为空")
    if len(data) > MAX_IMAGE_SIZE:
        return error("图片大小不能超过 10MB")

    file_name = text_or_none(file.filename) or "image.png"
    content_type = text_or_none(file.content_type) or "image/png"
    if not content_type.lower().startswith("image/") and not file_name.lower().endswith(IMAGE_EXTENSIONS):
        return error("仅支持上传图片文件")

    object_name = f"images/uploads/{uuid.uuid4().hex}{_extension_for(file_name, content_type)}"
    try:
        url = minio_service.upload_from_bytes(data, object_name, content_type)
    except Exception as exc:
        return error(f"图片上传失败: {exc}")
    return success(
        {
            "url": url,
            "fileName": file_name,
            "contentType": content_type,
            "size": len(data),
        }
    )
