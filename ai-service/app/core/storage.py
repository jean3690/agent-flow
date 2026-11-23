"""Local storage implementation shared by APIs and nodes, with separate per-user roots.

All paths exposed to workflows are *relative* to the configured storage root
(``AI_FILE_DIR``, falling back to ``AI_OUTPUT_DIR``).  Absolute paths and
``..`` segments are rejected so a workflow cannot read or overwrite arbitrary
files on the host.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import shutil
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlsplit

from app.config import Settings


class StorageError(Exception):
    """Base error for file-storage operations."""


class FileNotFoundStorageError(StorageError):
    """Raised when a requested file does not exist inside a storage root."""


DEFAULT_UPLOAD_NAME = "upload.bin"
_MAX_NAME_LENGTH = 120
_PRIVATE_DIR = ".users"
_MIME_OVERRIDES = {
    ".md": "text/markdown; charset=utf-8",
    ".markdown": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}


def storage_roots(settings: Settings) -> list[Path]:
    """Return every readable storage root, de-duplicated and resolved.

    Media nodes historically write into ``output_dir`` while user uploads may
    live in a separate ``file_dir``.  Read operations look in both places so
    a file produced by ``image_generate`` can also be consumed by ``file_read``.
    """

    if settings._storage_owner_id is None and not settings._storage_legacy:
        raise StorageError("文件操作缺少已绑定的用户或历史只读上下文")
    roots: list[Path] = []
    for path in (settings.files_dir, settings.audio_dir):
        if settings._storage_owner_id is not None and (path.is_symlink() or path.parent.is_symlink()):
            raise StorageError("用户存储目录不能使用符号链接")
        resolved = path.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def normalize_relative_path(ref: str) -> str:
    """Normalize a user supplied path / URL into a safe relative POSIX path."""

    raw = (ref or "").strip()
    if not raw:
        raise StorageError("文件路径不能为空")

    if raw.startswith(("/files/", "/api/files/")):
        raw = urlsplit(raw).path
    if "://" in raw:
        parsed = urlparse(raw)
        raw = unquote(parsed.path)
    else:
        raw = unquote(raw)

    raw = raw.replace("\\", "/")
    for prefix in ("/api/files/", "/files/", "files/"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    if raw.startswith("/"):
        raise StorageError("仅支持存储目录内的相对路径")

    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise StorageError("非法文件路径：不允许包含 ..")
        if "\x00" in part:
            raise StorageError("非法文件路径：包含空字符")
        if ":" in part or any(ord(char) < 32 or ord(char) == 127 for char in part):
            raise StorageError("非法文件路径：包含控制字符或设备路径")
        parts.append(part)
    if not parts:
        raise StorageError("文件路径不能为空")
    return "/".join(parts)


def _is_within(root: Path, candidate: Path) -> bool:
    return candidate == root or root in candidate.parents


def user_storage(settings: Settings, user_id: int | None) -> Settings:
    """Bind immutable runtime storage roots to a verified user; never fall back to shared files."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or not 1 <= user_id <= 9_223_372_036_854_775_807:
        raise StorageError("文件操作缺少有效用户上下文")
    if settings._storage_owner_id is not None:
        if settings._storage_owner_id != user_id:
            raise StorageError("文件用户上下文不一致")
        return settings
    roots = []
    for root in (settings.files_dir, settings.audio_dir):
        base = root.resolve()
        private = base / _PRIVATE_DIR
        owner = private / str(user_id)
        if private.is_symlink() or owner.is_symlink():
            raise StorageError("用户存储目录不能使用符号链接")
        roots.append(owner)
    scoped = settings.model_copy(update={"file_dir": str(roots[0]), "output_dir": str(roots[1])})
    scoped._storage_owner_id = user_id
    return scoped


def legacy_storage(settings: Settings) -> Settings:
    scoped = settings.model_copy()
    scoped._storage_legacy = True
    return scoped


def scoped_relative_path(settings: Settings, ref: str) -> str:
    rel = normalize_relative_path(ref)
    parts = rel.split("/")
    if _PRIVATE_DIR in parts:
        raise FileNotFoundStorageError("文件不存在")
    if parts[0] == "users":
        if len(parts) < 3 or parts[1] != str(settings._storage_owner_id):
            raise FileNotFoundStorageError("文件不存在")
        rel = "/".join(parts[2:])
    elif parts[0] == "legacy":
        if not settings._storage_legacy or len(parts) < 2:
            raise FileNotFoundStorageError("文件不存在")
        rel = "/".join(parts[1:])
    return rel


def storage_url(settings: Settings, rel: str) -> str:
    prefix = f"users/{settings._storage_owner_id}/" if settings._storage_owner_id is not None else "legacy/" if settings._storage_legacy else ""
    return "/files/" + quote(prefix + rel, safe="/")


def media_target(settings: Settings, name: str) -> Path:
    """Media writes use the same scoped and symlink-safe path rules as file nodes."""
    if settings._storage_owner_id is None:
        raise StorageError("媒体生成缺少有效用户上下文")
    media_settings = settings.model_copy(update={"file_dir": str(settings.audio_dir)})
    return resolve_for_write(media_settings, name)[0]


def is_local_file_reference(ref: str) -> bool:
    return ref.startswith(("/files/", "/api/files/")) or "://" not in ref and not ref.startswith(("data:", "oss:"))


def model_image_reference(settings: Settings, ref: str) -> str:
    """Cloud models cannot fetch authenticated local URLs; encode only the verified owner's image."""
    if not ref:
        return ""
    if not is_local_file_reference(ref):
        if ref.startswith("data:image/") or urlsplit(ref).scheme.lower() in {"https", "http"}:
            return ref
        raise StorageError("图片引用只支持用户文件、data image 或 HTTP(S) 地址")
    path, _ = resolve_existing(settings, ref)
    mime = guess_content_type(path.name)
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}:
        raise StorageError("本地图片格式不受支持")
    if path.stat().st_size > max(1, settings.max_upload_mb) * 1024 * 1024:
        raise StorageError("本地图片超过大小限制")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _no_symlinks(root: Path, candidate: Path) -> bool:
    current = root
    for part in candidate.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def resolve_existing(settings: Settings, ref: str) -> tuple[Path, str]:
    """Resolve an existing file in any storage root."""

    rel = scoped_relative_path(settings, ref)
    for root in storage_roots(settings):
        raw = root / rel
        if not _no_symlinks(root, raw):
            continue
        candidate = raw.resolve()
        if not _is_within(root, candidate):
            continue
        if candidate.is_file():
            return candidate, rel
    raise FileNotFoundStorageError(f"文件不存在: {rel}")


def resolve_for_write(settings: Settings, ref: str) -> tuple[Path, str]:
    """Resolve a target path under the writable storage root."""

    if settings._storage_legacy:
        raise StorageError("历史共享文件只读")
    rel = scoped_relative_path(settings, ref)
    root = storage_roots(settings)[0]
    raw = root / rel
    if not _no_symlinks(root, raw):
        raise StorageError("文件路径不能使用符号链接")
    target = raw.resolve()
    if not _is_within(root, target):
        raise StorageError("非法文件路径：超出存储目录")
    if target.exists() and target.is_dir():
        raise StorageError(f"目标是目录，不能写入: {rel}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target, rel


def safe_upload_name(original_name: str | None) -> str:
    """Turn a browser supplied filename into a safe, readable file name."""

    candidate = (original_name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    candidate = "".join(ch for ch in candidate if ch >= " " and ch != "\x7f")
    if not candidate:
        candidate = DEFAULT_UPLOAD_NAME
    if len(candidate) <= _MAX_NAME_LENGTH:
        return candidate

    suffix = Path(candidate).suffix
    stem = candidate[: max(1, _MAX_NAME_LENGTH - len(suffix))]
    return stem + suffix


def guess_content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in _MIME_OVERRIDES:
        return _MIME_OVERRIDES[suffix]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def file_metadata(path: Path, rel: str, *, original_name: str | None = None, settings: Settings | None = None) -> dict[str, Any]:
    stat = path.stat()
    name = Path(rel).name
    quoted = quote(rel, safe="/")
    return {
        "name": rel,
        "fileName": name,
        "originalName": original_name or name,
        "path": rel,
        "url": storage_url(settings, rel) if settings is not None else f"/files/{quoted}",
        "size": stat.st_size,
        "contentType": guess_content_type(rel),
        "createdAt": int(stat.st_ctime * 1000),
        "updatedAt": int(stat.st_mtime * 1000),
    }


def _unique_name(settings: Settings, rel: str) -> str:
    root = storage_roots(settings)[0]
    target = root / rel
    if not target.exists():
        return rel
    suffix = Path(rel).suffix
    stem = rel[: len(rel) - len(suffix)] if suffix else rel
    while True:
        candidate = f"{stem}-{uuid.uuid4().hex[:8]}{suffix}"
        if not (root / candidate).exists():
            return candidate


def save_bytes(
    settings: Settings,
    data: bytes,
    *,
    name: str = "",
    overwrite: bool = True,
    append: bool = False,
) -> dict[str, Any]:
    """Write bytes under the storage root and return file metadata."""

    rel = scoped_relative_path(settings, name or f"upload-{uuid.uuid4().hex}.bin")
    target, rel = resolve_for_write(settings, rel)
    if target.exists() and not overwrite and not append:
        raise StorageError(f"文件已存在: {rel}")
    if append:
        with target.open("ab") as handle:
            handle.write(data)
    else:
        target.write_bytes(data)
    return file_metadata(target, rel, settings=settings)


def save_upload(
    settings: Settings,
    data: bytes,
    *,
    original_name: str | None = None,
    name: str = "",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Persist an uploaded file, keeping the original name when possible."""

    rel = scoped_relative_path(settings, name) if name.strip() else safe_upload_name(original_name)
    if not overwrite:
        rel = _unique_name(settings, rel)
    metadata = save_bytes(settings, data, name=rel, overwrite=True)
    metadata["originalName"] = safe_upload_name(original_name or rel)
    return metadata


def save_text(
    settings: Settings,
    content: str,
    *,
    name: str,
    encoding: str = "utf-8",
    overwrite: bool = True,
    append: bool = False,
) -> dict[str, Any]:
    try:
        data = (content or "").encode(encoding)
    except LookupError as exc:
        raise StorageError(f"不支持的编码: {encoding}") from exc
    return save_bytes(settings, data, name=name, overwrite=overwrite, append=append)


def read_text(
    settings: Settings,
    ref: str,
    *,
    encoding: str = "utf-8",
    max_chars: int = 200_000,
) -> dict[str, Any]:
    path, rel = resolve_existing(settings, ref)
    data = path.read_bytes()
    try:
        text = data.decode(encoding, errors="replace")
    except LookupError as exc:
        raise StorageError(f"不支持的编码: {encoding}") from exc

    truncated = False
    if max_chars and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True

    metadata = file_metadata(path, rel, settings=settings)
    return {
        **metadata,
        "text": text,
        "content": text,
        "encoding": encoding,
        "charCount": len(text),
        "truncated": truncated,
    }


def list_files(settings: Settings, *, prefix: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """List files from every storage root, newest first."""

    normalized_prefix = ""
    if prefix.strip():
        normalized_prefix = scoped_relative_path(settings, prefix)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = max(1, min(int(limit or 500), 5000))
    for root in storage_roots(settings):
        for path in _walk_files(root):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if normalized_prefix and not rel.startswith(normalized_prefix):
                continue
            if rel in seen:
                continue
            seen.add(rel)
            try:
                items.append(file_metadata(path, rel, settings=settings))
            except OSError:
                continue
    items.sort(key=lambda item: item.get("updatedAt", 0), reverse=True)
    return items[:max_items]


def _walk_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = [name for name in names if name != _PRIVATE_DIR and not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_file() and _no_symlinks(root, path):
                yield path


def delete_file(settings: Settings, ref: str) -> dict[str, Any]:
    if settings._storage_legacy:
        raise StorageError("历史共享文件只读")
    path, rel = resolve_existing(settings, ref)
    metadata = file_metadata(path, rel, settings=settings)
    path.unlink()
    _prune_empty_dirs(path.parent, storage_roots(settings))
    return metadata


def _prune_empty_dirs(directory: Path, roots: list[Path]) -> None:
    """Remove empty sub-directories created by file_write, never the root."""

    for root in roots:
        if not _is_within(root, directory) or directory == root:
            continue
        current = directory
        while current != root and _is_within(root, current):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
        return


def copy_stream(*, src: Any, dst: Path) -> int:
    """Small helper used by tests / future streaming uploads."""

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as handle:
        shutil.copyfileobj(src, handle)
    return dst.stat().st_size


def timestamp_ms() -> int:
    return int(time.time() * 1000)
