from __future__ import annotations

import math
import time
import uuid
import wave
from pathlib import Path
from typing import Any

import httpx

from app.core.template import build_names, render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.schemas.flow import FlowNode

_SAMPLE_RATE = 24_000


@register
class TtsNodeExecutor(NodeExecutor):
    type = "tts"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        provider = (config.get("provider") or "openai").lower()
        voice = config.get("voice") or "alloy"
        audio_format = (config.get("format") or "mp3").lower()
        names = build_names(state.get("input") or {}, state.get("variables") or {}, state.get("outputs") or {})
        text = render(config.get("text") or "{{input}}", names, strict=True)
        if not text.strip():
            text = "（空文本）"

        filename = f"{uuid.uuid4().hex}.{audio_format if provider != 'mock' else 'wav'}"
        target = Path(ctx.settings.audio_dir) / filename
        api_key, base_url = ctx.credentials(provider)

        if provider != "mock" and api_key:
            base_url = base_url or "https://api.openai.com/v1"
            payload = {
                "model": config.get("model") or "tts-1",
                "input": text[:4000],
                "voice": voice,
                "response_format": "mp3" if audio_format not in {"mp3", "wav", "opus", "aac", "flac"} else audio_format,
            }
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{base_url.rstrip('/')}/audio/speech", json=payload, headers=headers)
                resp.raise_for_status()
                target.write_bytes(resp.content)
            duration_ms = int(max(1000, len(text) * 90))
            mock = False
        else:
            duration_ms = _write_silence(target, len(text))
            mock = True
            ctx.emit("node_log", nodeId=node.id, level="info", message="TTS 未配置真实厂商，已生成占位音频")

        return {
            "audioUrl": f"/files/{filename}",
            "durationMs": duration_ms,
            "format": target.suffix.lstrip("."),
            "text": text,
            "mock": mock,
            "createdAt": int(time.time() * 1000),
        }


def _write_silence(path: Path, text_length: int) -> int:
    seconds = min(8.0, max(0.8, text_length * 0.08))
    frames = int(_SAMPLE_RATE * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        handle.writeframes(b"\x00\x00" * frames)
    return int(math.ceil(seconds * 1000))
