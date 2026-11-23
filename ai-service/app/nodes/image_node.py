from __future__ import annotations

import base64
import hashlib
import struct
import time
import uuid
import zlib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.errors import NodeExecutionError
from app.core.storage import (
    is_local_file_reference,
    media_target,
    model_image_reference,
    scoped_relative_path,
    storage_url,
)
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_DEFAULT_SIZE = "1024x1024"


@register
class ImageNodeExecutor(NodeExecutor):
    """图像生成：OpenAI 兼容接口为主，StepFun / 火山方舟走各自端点。"""

    type = "image_generate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "mock").lower()
        model = config.get("model") or "gpt-image-1"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)
        reference = render(str(config.get("referenceImageUrl") or ""), names).strip()
        size = str(config.get("size") or _DEFAULT_SIZE)
        filename = f"{uuid.uuid4().hex}.png"
        storage = ctx.storage
        target = media_target(storage, filename)
        if reference and is_local_file_reference(reference):
            scoped_relative_path(storage, reference)

        if provider == "mock" or not ctx.credentials(provider)[0]:
            target.write_bytes(_placeholder_png(prompt))
            ctx.emit("node_log", nodeId=node.id, level="info", message="未配置图像厂商，已生成占位图片")
            return self._result(storage_url(storage, filename), provider, model, size, mock=True)

        api_key, base_url = ctx.credentials(provider)
        reference = model_image_reference(storage, reference)
        try:
            if provider == "step":
                image_url, b64 = await _step_image(api_key, base_url, model, prompt, size, reference)
            elif provider_aliases(provider) == "volcengine":
                image_url, b64 = await _volcengine_image(api_key, base_url, model, prompt, size, reference)
            else:
                image_url, b64 = await _openai_image(api_key, base_url, model, prompt, size)
            await _persist_image(target, image_url, b64)
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"图像生成失败: {exc}") from exc

        return self._result(storage_url(storage, filename), provider, model, size, mock=False)

    def _result(self, url: str, provider: str, model: str, size: str, mock: bool) -> dict[str, Any]:
        return {
            "imageUrl": url,
            "provider": provider,
            "model": model,
            "size": size,
            "createdAt": int(time.time() * 1000),
            "mock": mock,
        }


def provider_aliases(provider: str) -> str:
    return {"ark": "volcengine", "agent_plan": "volcengine"}.get(provider.lower(), provider.lower())


async def _openai_image(api_key: str, base_url: str | None, model: str,
                        prompt: str, size: str) -> tuple[str | None, str | None]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=120)
    response = await client.images.generate(model=model, prompt=prompt[:4000], size=size, n=1)
    item = response.data[0]
    if not getattr(item, "b64_json", None) and not getattr(item, "url", None):
        raise RuntimeError("图像接口未返回图片数据")
    return getattr(item, "url", None), getattr(item, "b64_json", None)


def _step_endpoint(base_url: str | None, model: str) -> str:
    base = (base_url or "https://api.stepfun.com/v1").rstrip("/")
    if base.endswith("/images/generations"):
        return base
    if model.startswith("step-image-edit"):
        parts = urlsplit(base)
        return f"{parts.scheme}://{parts.netloc}/step_plan/v1/images/generations"
    if not base.endswith("/v1"):
        base += "/v1"
    return f"{base}/images/generations"


async def _step_image(api_key: str, base_url: str | None, model: str, prompt: str,
                      size: str, reference: str) -> tuple[str | None, str | None]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt[:512],
        "response_format": "url",
        "n": 1,
        "size": size if "x" in size else _DEFAULT_SIZE,
    }
    if model.startswith("step-image-edit"):
        body["text_mode"] = True
    if reference:
        body["image"] = reference
    return await _post_image(_step_endpoint(base_url, model), api_key, body)


async def _volcengine_image(api_key: str, base_url: str | None, model: str, prompt: str,
                            size: str, reference: str) -> tuple[str | None, str | None]:
    base = (base_url or "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt[:4000],
        "response_format": "url",
        "output_format": "png",
        "watermark": False,
        "stream": False,
        "size": size,
    }
    if reference:
        body["image"] = reference
    return await _post_image(f"{base}/images/generations", api_key, body)


async def _post_image(endpoint: str, api_key: str, body: dict[str, Any]) -> tuple[str | None, str | None]:
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        response = await client.post(endpoint, json=body, headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        data = response.json() or {}
    items = data.get("data") or []
    if not items:
        raise RuntimeError("图像接口未返回图片数据")
    item = items[0] if isinstance(items[0], dict) else {}
    return item.get("url"), item.get("b64_json")


async def _persist_image(target: Path, image_url: str | None, b64: str | None) -> None:
    if b64:
        target.write_bytes(base64.b64decode(b64))
        return
    if not image_url:
        raise RuntimeError("图像接口未返回图片数据")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
        remote = await http.get(image_url)
        remote.raise_for_status()
        target.write_bytes(remote.content)


def _placeholder_png(prompt: str) -> bytes:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    rgb = (digest[0], digest[1], digest[2])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    width = height = 256
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
