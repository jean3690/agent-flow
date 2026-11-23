from __future__ import annotations

import io
import logging
import os
import uuid
from urllib.parse import urlparse

import httpx

from .settings import settings

logger = logging.getLogger("agentflow.minio")


class MinioService:
    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from minio import Minio

            parsed = urlparse(settings.minio_endpoint)
            self._client = Minio(
                parsed.netloc or settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=(parsed.scheme == "https"),
            )
        return self._client

    def _ensure_bucket(self) -> None:
        client = self._get_client()
        if not client.bucket_exists(settings.minio_bucket_name):
            client.make_bucket(settings.minio_bucket_name)
            logger.info("Created MinIO bucket: %s", settings.minio_bucket_name)

    def upload_file(self, object_name: str, data: bytes, content_type: str, size: int | None = None) -> str:
        self._ensure_bucket()
        client = self._get_client()
        client.put_object(
            settings.minio_bucket_name,
            object_name,
            io.BytesIO(data),
            length=len(data) if size is None else size,
            content_type=content_type,
        )
        logger.info("Uploaded to MinIO: %s", object_name)
        return f"{settings.minio_public_url}/{settings.minio_bucket_name}/{object_name}"

    def upload_from_bytes(self, data: bytes, object_name: str, content_type: str) -> str:
        return self.upload_file(object_name, data, content_type, len(data))

    def upload_from_url(self, file_url: str, object_name: str, content_type: str) -> str:
        if not file_url:
            return file_url
        with httpx.stream("GET", file_url, timeout=120.0, follow_redirects=True) as response:
            response.raise_for_status()
            data = response.read()
        return self.upload_from_bytes(data, object_name, content_type)

    def new_object_name(self, folder: str, extension: str) -> str:
        return f"{folder}/{uuid.uuid4().hex}{extension}"


minio_service = MinioService()
