from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any
from urllib.parse import quote

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
from app.nodes.image_node import _placeholder_png, provider_aliases
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_POLL_INTERVAL_SECONDS = 3
_POLL_LIMIT = 60


@register
class VideoNodeExecutor(NodeExecutor):
    """视频生成：提交任务 + 轮询。

    厂商适配：
      agnes      POST {base}/v1/videos -> video_id；GET /agnesapi 或 /v1/videos/{id}
      volcengine POST {base}/contents/generations/tasks -> id；GET /contents/generations/tasks/{id}
      其他       POST {base}/video/generations -> id；GET /video/generations/{id}
    """

    type = "video_generate"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "mock").lower()
        model = config.get("model") or "video-01"
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        prompt = render(config.get("prompt") or "{{input}}", names, strict=True)
        reference = render(str(config.get("referenceImageUrl") or ""), names).strip()
        duration = max(1, min(int(config.get("duration") or 5), 15))
        resolution = str(config.get("resolution") or "").strip()
        ratio = str(config.get("ratio") or "adaptive").strip() or "adaptive"
        storage = ctx.storage
        if reference and is_local_file_reference(reference):
            scoped_relative_path(storage, reference)

        if ctx.mock_for(provider):
            filename = f"{uuid.uuid4().hex}.png"
            target = media_target(storage, filename)
            target.write_bytes(_placeholder_png(prompt))
            ctx.emit("node_log", nodeId=node.id, level="info", message="未配置视频厂商，已生成占位海报")
            return {
                "videoUrl": "",
                "posterUrl": storage_url(storage, filename),
                "text": "视频生成需要配置支持视频接口的服务商；当前为占位海报。",
                "provider": "mock",
                "model": model,
                "createdAt": int(time.time() * 1000),
                "mock": True,
            }

        api_key, base_url = ctx.credentials(provider)
        reference = model_image_reference(storage, reference)
        canonical = provider_aliases(provider)
        try:
            if canonical == "agnes":
                video_url, cover_url = await _agnes_video(
                    node.id, ctx, api_key, base_url, model, prompt, reference, duration)
            elif canonical == "volcengine":
                video_url, cover_url = await _volcengine_video(
                    node.id, ctx, api_key, base_url, model, prompt, reference, duration, resolution, ratio)
            else:
                video_url, cover_url = await _generic_video(
                    node.id, ctx, api_key, base_url, model, prompt)
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface provider errors to the run
            raise NodeExecutionError(node.id, f"视频生成失败: {exc}") from exc

        filename = f"{uuid.uuid4().hex}.mp4"
        target = media_target(storage, filename)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            remote = await client.get(video_url)
            remote.raise_for_status()
            target.write_bytes(remote.content)

        return {
            "videoUrl": storage_url(storage, filename),
            "posterUrl": cover_url or "",
            "provider": provider,
            "model": model,
            "createdAt": int(time.time() * 1000),
            "mock": False,
        }


async def _generic_video(node_id: str, ctx: NodeContext, api_key: str, base_url: str | None,
                         model: str, prompt: str) -> tuple[str, str]:
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
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
            ctx.emit("node_log", nodeId=node_id, level="info", message=f"视频任务状态: {status or 'unknown'}")
            if status in {"succeeded", "success", "completed"}:
                video_url = data.get("video_url") or data.get("url")
                if not video_url:
                    raise RuntimeError("任务完成但未返回视频地址")
                return video_url, str(data.get("cover_url") or "")
            if status in {"failed", "error"}:
                raise RuntimeError(str(data.get("error") or "视频生成失败"))
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"视频生成超时（>{_POLL_LIMIT * _POLL_INTERVAL_SECONDS}s）")


def _agnes_num_frames(duration: int) -> int:
    candidate = duration * 24 + 1
    normalized = round((candidate - 1) / 8.0) * 8 + 1
    return max(9, min(441, normalized))


def _agnes_base(base_url: str | None) -> str:
    base = (base_url or "https://apihub.agnes-ai.com").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base


async def _agnes_video(node_id: str, ctx: NodeContext, api_key: str, base_url: str | None,
                       model: str, prompt: str, reference: str, duration: int) -> tuple[str, str]:
    base = _agnes_base(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt[:4000],
        "num_frames": _agnes_num_frames(duration),
        "frame_rate": 24,
    }
    if reference:
        body["image"] = reference
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        response = await client.post(f"{base}/v1/videos", json=body, headers=headers)
        response.raise_for_status()
        created = response.json() or {}
        task_id = created.get("video_id") or created.get("videoId") or created.get("task_id") or created.get("id")
        if not task_id:
            raise RuntimeError("Agnes 视频接口未返回任务 id")

        for _ in range(_POLL_LIMIT):
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            if str(task_id).startswith("video_"):
                query = f"{base}/agnesapi?video_id={quote(str(task_id))}&model_name={quote(model)}"
            else:
                query = f"{base}/v1/videos/{quote(str(task_id))}"
            poll = await client.get(query, headers=headers)
            poll.raise_for_status()
            data = poll.json() or {}
            status = str(data.get("status") or data.get("task_status") or "").lower()
            ctx.emit("node_log", nodeId=node_id, level="info", message=f"Agnes 视频任务状态: {status or 'unknown'}")
            if any(word in status for word in ("success", "succeed", "completed")):
                video_url = data.get("video_url") or data.get("videoUrl") or data.get("url")
                if not video_url:
                    raise RuntimeError("Agnes 任务完成但未返回视频地址")
                cover = data.get("cover_url") or data.get("poster_url") or data.get("last_frame_url") or ""
                return video_url, str(cover)
            if any(word in status for word in ("fail", "error", "cancel")):
                raise RuntimeError(str(data.get("error") or data.get("message") or "视频生成失败"))
    raise RuntimeError(f"视频生成超时（>{_POLL_LIMIT * _POLL_INTERVAL_SECONDS}s）")


async def _volcengine_video(node_id: str, ctx: NodeContext, api_key: str, base_url: str | None,
                            model: str, prompt: str, reference: str, duration: int,
                            resolution: str, ratio: str) -> tuple[str, str]:
    base = (base_url or "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt[:4000]}]
    if reference:
        content.append({"type": "image_url", "image_url": {"url": reference}})
    body: dict[str, Any] = {
        "model": model,
        "content": content,
        "duration": duration,
        "ratio": ratio,
        "generate_audio": True,
        "watermark": False,
    }
    if resolution:
        body["resolution"] = resolution
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        response = await client.post(f"{base}/contents/generations/tasks", json=body, headers=headers)
        response.raise_for_status()
        created = response.json() or {}
        task_id = created.get("id") or created.get("task_id") or created.get("taskId")
        if not task_id:
            raise RuntimeError("火山方舟视频接口未返回任务 id")

        for _ in range(_POLL_LIMIT):
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            poll = await client.get(f"{base}/contents/generations/tasks/{quote(str(task_id))}", headers=headers)
            poll.raise_for_status()
            data = poll.json() or {}
            status = str(data.get("status") or data.get("task_status") or "").lower()
            ctx.emit("node_log", nodeId=node_id, level="info", message=f"火山方舟视频任务状态: {status or 'unknown'}")
            if any(word in status for word in ("success", "succeed", "completed")):
                video_url = data.get("video_url") or data.get("videoUrl") or data.get("url")
                if not video_url:
                    raise RuntimeError("任务完成但未返回视频地址")
                cover = data.get("last_frame_url") or data.get("cover_url") or data.get("poster_url") or ""
                return video_url, str(cover)
            if any(word in status for word in ("fail", "error", "cancel")):
                raise RuntimeError(str(data.get("error") or data.get("message") or "视频生成失败"))
    raise RuntimeError(f"视频生成超时（>{_POLL_LIMIT * _POLL_INTERVAL_SECONDS}s）")
