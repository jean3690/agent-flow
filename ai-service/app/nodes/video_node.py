from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.image_node import _placeholder_png
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_POLL_INTERVAL_SECONDS = 3
_POLL_LIMIT = 60


@register
class VideoNodeExecutor(NodeExecutor):
    """视频生成节点。

    mock / 未配置 Key：生成占位海报图（真实视频需厂商接口）。
    真实调用走「提交任务 + 轮询」的通用约定：
      POST {base}/video/generations { model, prompt } -> { id }
      GET  {base}/video/generations/{id} -> { status, video_url }
    不同厂商路径/字段不一致时需要适配层。
    """

    type = "video_generate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "mock").lower()
        model = config.get("model") or "video-01"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)

        if ctx.mock_for(provider):
            filename = f"{uuid.uuid4().hex}.png"
            target = Path(ctx.settings.audio_dir) / filename
            target.write_bytes(_placeholder_png(prompt))
            ctx.emit("node_log", nodeId=node.id, level="info", message="未配置视频厂商，已生成占位海报")
            return {
                "videoUrl": "",
                "posterUrl": f"/files/{filename}",
                "text": "视频生成需要配置支持视频接口的服务商；当前为占位海报。",
                "provider": "mock",
                "model": model,
                "mock": True,
            }

        api_key, base_url = ctx.credentials(provider)
        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            video_url = await self._generate(base, headers, model, prompt)
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"视频生成失败: {exc}") from exc

        filename = f"{uuid.uuid4().hex}.mp4"
        target = Path(ctx.settings.audio_dir) / filename
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            remote = await client.get(video_url)
            remote.raise_for_status()
            target.write_bytes(remote.content)

        return {
            "videoUrl": f"/files/{filename}",
            "posterUrl": "",
            "provider": provider,
            "model": model,
            "createdAt": int(time.time() * 1000),
            "mock": False,
        }

    async def _generate(self, base: str, headers: dict, model: str, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base}/video/generations",
                json={"model": model, "prompt": prompt[:4000]},
                headers=headers,
            )
            response.raise_for_status()
            job_id = (response.json() or {}).get("id")
            if not job_id:
                raise RuntimeError("视频接口未返回任务 id")

            for _ in range(_POLL_LIMIT):
                poll = await client.get(f"{base}/video/generations/{job_id}", headers=headers)
                poll.raise_for_status()
                data = poll.json() or {}
                status = str(data.get("status") or "").lower()
                if status in {"succeeded", "success", "completed"}:
                    video_url = data.get("video_url") or data.get("url")
                    if not video_url:
                        raise RuntimeError("任务完成但未返回视频地址")
                    return video_url
                if status in {"failed", "error"}:
                    raise RuntimeError(str(data.get("error") or "视频生成失败"))
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        raise RuntimeError(f"视频生成超时（>{_POLL_LIMIT * _POLL_INTERVAL_SECONDS}s）")
