from __future__ import annotations

import base64
import hashlib
import struct
import time
import uuid
import zlib
from pathlib import Path
from typing import Any

import httpx

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode


@register
class ImageNodeExecutor(NodeExecutor):
    type = "image_generate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "mock").lower()
        model = config.get("model") or "gpt-image-1"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)
        size = str(config.get("size") or "1024x1024")
        filename = f"{uuid.uuid4().hex}.png"
        target = Path(ctx.settings.audio_dir) / filename

        if provider == "mock" or not ctx.credentials(provider)[0]:
            target.write_bytes(_placeholder_png(prompt))
            ctx.emit("node_log", nodeId=node.id, level="info", message="未配置图像厂商，已生成占位图片")
            return self._result(filename, provider, model, size, mock=True)

        api_key, base_url = ctx.credentials(provider)
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=120)
            response = await client.images.generate(model=model, prompt=prompt[:4000], size=size, n=1)
            item = response.data[0]
            if getattr(item, "b64_json", None):
                target.write_bytes(base64.b64decode(item.b64_json))
            elif getattr(item, "url", None):
                async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
                    remote = await http.get(item.url)
                    remote.raise_for_status()
                    target.write_bytes(remote.content)
            else:
                raise RuntimeError("图像接口未返回图片数据")
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"图像生成失败: {exc}") from exc

        return self._result(filename, provider, model, size, mock=False)

    def _result(self, filename: str, provider: str, model: str, size: str, mock: bool) -> dict[str, Any]:
        return {
            "imageUrl": f"/files/{filename}",
            "provider": provider,
            "model": model,
            "size": size,
            "createdAt": int(time.time() * 1000),
            "mock": mock,
        }


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
