from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.ai_client import AiClient, get_ai
from app.errors import BizError, forbidden, not_found
from app.security import CurrentUser

OWNER_PATTERN = re.compile(r"[1-9][0-9]*")


@dataclass
class Download:
    name: str
    content: bytes


@dataclass
class Scope:
    owner_id: int
    legacy: bool
    path: str


class FileService:
    def __init__(self, ai: AiClient | None = None) -> None:
        self.ai = ai or get_ai()

    def list_files(self, prefix: str, limit: int, owner_id: int | None, legacy: bool,
                   user: CurrentUser) -> list[Any]:
        owner = owner_id if owner_id is not None else user.id
        self._authorize(owner, legacy, user)
        selected = "" if not prefix or not prefix.strip() else self._safe_path(prefix)
        if legacy and selected:
            selected = "legacy/" + selected
        capped = max(1, min(int(limit or 500), 5000))
        path = f"/v1/files?limit={capped}&prefix={quote(selected, safe='')}"
        result = self.ai.file_json("GET", path, None, owner, legacy) or []
        return result if isinstance(result, list) else []

    def upload(self, name: str, content: bytes, content_type: str | None, user: CurrentUser) -> Any:
        scope = self._scope(name, user, True)
        return self.ai.file_upload(scope.path, content, content_type, scope.owner_id)

    def write_text(self, payload: dict[str, Any], user: CurrentUser) -> Any:
        scope = self._scope(payload.get("name"), user, True)
        body = {
            "name": scope.path,
            "content": payload.get("content", ""),
            "encoding": payload.get("encoding") or "utf-8",
            "overwrite": payload.get("overwrite", True),
            "append": payload.get("append", False),
        }
        return self.ai.file_json("POST", "/v1/files/text", body, scope.owner_id, False)

    def delete(self, name: str, user: CurrentUser) -> Any:
        scope = self._scope(name, user, True)
        return self.ai.file_json("DELETE", "/v1/files/" + self._encode(scope.path), None, scope.owner_id, False)

    def download(self, name: str, user: CurrentUser) -> Download:
        scope = self._scope(name, user, False)
        path = "legacy/" + scope.path if scope.legacy else scope.path
        content = self.ai.file_download("/files/" + self._encode(path), scope.owner_id, scope.legacy)
        filename = scope.path[scope.path.rfind("/") + 1 :]
        return Download(filename, content)

    def _scope(self, name: str | None, user: CurrentUser, write: bool) -> Scope:
        path = self._safe_path(name)
        owner = user.id
        legacy = False
        if path.startswith("users/"):
            parts = path.split("/", 2)
            if len(parts) < 3 or not OWNER_PATTERN.fullmatch(parts[1]):
                raise not_found("文件不存在")
            owner = int(parts[1])
            path = parts[2]
        elif path.startswith("legacy/"):
            legacy = True
            path = path[len("legacy/") :]
        self._authorize(owner, legacy, user)
        if legacy and write:
            raise forbidden("历史共享文件只读，请重新上传到用户目录")
        return Scope(owner, legacy, path)

    @staticmethod
    def _authorize(owner: int | None, legacy: bool, user: CurrentUser) -> None:
        if owner is None or owner <= 0:
            raise not_found("文件不存在")
        if legacy and not user.is_admin:
            raise not_found("文件不存在")
        if owner != user.id and not user.is_admin:
            raise not_found("文件不存在")

    @staticmethod
    def _safe_path(name: str | None) -> str:
        path = (name or "").replace("\\", "/")
        path = re.sub(r"^/+", "", path)
        if not path.strip():
            raise BizError("文件路径不能为空")
        parts = [part for part in path.split("/") if part]
        for part in parts:
            if part == ".users":
                raise not_found("文件不存在")
            if part in {".", ".."} or ":" in part or any(ord(ch) < 32 or ord(ch) == 127 for ch in part):
                raise BizError("非法文件路径")
        return "/".join(parts)

    @staticmethod
    def _encode(path: str) -> str:
        return "/".join(quote(part, safe="") for part in path.split("/"))


def media_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".html", ".htm")):
        return "text/html"
    if lower.endswith(".css"):
        return "text/css"
    if lower.endswith((".js", ".mjs")):
        return "text/javascript"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".md"):
        return "text/markdown"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".txt"):
        return "text/plain"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp4"):
        return "video/mp4"
    return "application/octet-stream"
