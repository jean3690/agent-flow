"""Native Bailian endpoints, separate from OpenAI-compatible chat."""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.core.web import _check_url

_WORKSPACE_HOST = re.compile(r"[a-zA-Z0-9-]+\.(?:cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com")
_LEGACY_HOSTS = {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"}
MAX_IMAGE_BYTES = 100 * 1024 * 1024


def api_origin(api_host: str, base_url: str = "", *, realtime: bool = False) -> str:
    raw = api_host.strip() or base_url.strip() or "https://dashscope.aliyuncs.com"
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    host = parts.hostname or ""
    if (parts.scheme != "https" or parts.username or parts.password or parts.port
            or parts.query or parts.fragment or not (_WORKSPACE_HOST.fullmatch(host) or host in _LEGACY_HOSTS)):
        raise ValueError("API Host 必须是百炼北京或新加坡的业务空间域名，不含端口、查询参数或凭据")
    if realtime and not _WORKSPACE_HOST.fullmatch(host):
        raise ValueError("实时语音翻译需要业务空间 API Host，例如 <WorkspaceId>.cn-beijing.maas.aliyuncs.com")
    return "https://" + host


def provider_error(data: dict) -> None:
    if data.get("code"):
        raise ValueError(f"百炼 {data['code']}: {str(data.get('message') or '调用失败')[:400]}")


async def upload_image(client: httpx.AsyncClient, origin: str, api_key: str, model: str, path: Path) -> str:
    response = await client.get(origin + "/api/v1/uploads", params={"action": "getPolicy", "model": model},
                                headers={"Authorization": f"Bearer {api_key}"})
    response.raise_for_status()
    payload = response.json()
    provider_error(payload)
    policy = payload["data"]
    host = urlsplit(policy["upload_host"])
    if host.scheme != "https" or not (host.hostname or "").endswith(".aliyuncs.com") or host.username or host.password:
        raise ValueError("百炼返回了不可信的文件上传地址")
    filename = uuid.uuid4().hex + path.suffix.lower()
    key = policy["upload_dir"].rstrip("/") + "/" + filename
    fields = {"OSSAccessKeyId": policy["oss_access_key_id"], "Signature": policy["signature"],
              "policy": policy["policy"], "x-oss-object-acl": policy["x_oss_object_acl"],
              "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"], "key": key,
              "success_action_status": "200"}
    # Never forward the long-term API key to the OSS upload host.
    with path.open("rb") as file:
        response = await client.post(policy["upload_host"], data=fields, files={"file": (filename, file)})
    response.raise_for_status()
    return "oss://" + key


async def download_image(client: httpx.AsyncClient, url: str, target: Path) -> None:
    await asyncio.to_thread(_check_url, url)
    size = 0
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with target.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ValueError("翻译图片超过 100 MB 限制")
                    file.write(chunk)
        from PIL import Image
        with Image.open(target) as image:
            if image.format != "JPEG":
                raise ValueError("百炼未返回有效的 JPG 翻译图片")
            image.verify()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
