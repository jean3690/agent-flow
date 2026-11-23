"""One-use, short-lived tickets for browser live translation via the platform WS bridge."""
from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from websockets.asyncio.client import connect

from app.api.skills import require_internal
from app.config import get_settings
from app.core.bailian import api_origin

router = APIRouter(prefix="/v1/translations", tags=["translations"])
MAX_MESSAGE = 64 * 1024
MAX_SECONDS = 600


class RealtimeRequest(BaseModel):
    provider: str = "qwen"
    model: str = "qwen3.8-livetranslate-flash-realtime"
    api_key: str = Field(default="", alias="apiKey", repr=False)
    base_url: str = Field(default="", alias="baseUrl")
    api_host: str = Field(default="", alias="apiHost")
    target_lang: str = Field(default="en", alias="targetLang", pattern=r"^[a-z]{2,3}(?:-[a-z]{2,4})?$")
    voice: str = Field(default="Tina", max_length=80)
    output_audio: bool = Field(default=True, alias="outputAudio")
    user_id: int = Field(alias="userId")
    model_config = {"populate_by_name": True, "extra": "forbid"}


@dataclass(repr=False)
class Ticket:
    request: RealtimeRequest
    key: str
    origin: str
    expires: float
    mock: bool


_TICKETS: dict[str, Ticket] = {}
_ACTIVE: dict[int, int] = {}


def consume_ticket(token: str) -> Ticket | None:
    ticket = _TICKETS.pop(token, None)
    return ticket if ticket and ticket.expires > time.monotonic() else None


@router.post("/realtime/sessions")
async def create_session(request: RealtimeRequest, x_internal_token: str = Header(default="")):
    require_internal(x_internal_token)
    now = time.monotonic()
    for token, ticket in list(_TICKETS.items()):
        if ticket.expires <= now:
            _TICKETS.pop(token, None)
    if len(_TICKETS) >= 64 or sum(t.request.user_id == request.user_id for t in _TICKETS.values()) >= 4:
        raise HTTPException(429, "待连接会话过多，请稍后再试")
    if request.provider not in {"qwen", "mock"} or request.model != "qwen3.8-livetranslate-flash-realtime":
        raise HTTPException(400, "实时翻译仅适配百炼 qwen3.8-livetranslate-flash-realtime 或 mock")
    settings = get_settings()
    key = request.api_key or settings.api_key_for("qwen")
    # Unlike normal demo workflows, live microphone capture never silently falls back to mock.
    mock = request.provider == "mock"
    origin = ""
    if not mock:
        if not key:
            raise HTTPException(400, "请先在模型配置中保存百炼 API Key，或显式选择模拟模式")
        try:
            origin = api_origin(request.api_host or settings.dashscope_api_host,
                                request.base_url or settings.base_url_for("qwen"), realtime=True)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    token = secrets.token_urlsafe(32)
    _TICKETS[token] = Ticket(request, key, origin, now + 60, mock)
    asyncio.get_running_loop().call_later(60, _TICKETS.pop, token, None)
    return {"data": {"ticket": token, "expiresIn": 60, "mock": mock,
                     "inputSampleRate": 16000, "outputSampleRate": 24000}}


def session_update(request: RealtimeRequest) -> dict:
    return {"type": "session.update", "session": {
        "input_modalities": ["audio"],
        "output_modalities": ["text", "audio"] if request.output_audio else ["text"],
        "audio": {"input": {"turn_detection": {"type": "speaker_detection", "threshold": 0.5}},
                  "output": {"voice": request.voice}},
        "translation": {"language": request.target_lang},
    }}


def audio_message(raw: str) -> dict:
    if len(raw.encode()) > MAX_MESSAGE:
        raise ValueError("音频消息超过 64 KB")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise TypeError("消息必须为 JSON 对象")
    if data.get("type") == "finish":
        return {"type": "session.finish"}
    if data.get("type") != "audio" or not isinstance(data.get("audio"), str):
        raise ValueError("仅接受 audio 或 finish 消息")
    audio = base64.b64decode(data["audio"], validate=True)
    if not audio or len(audio) % 2 or len(audio) > 16000:
        raise ValueError("音频必须是最多 500 ms 的 16 kHz 单声道 PCM16 小端数据")
    return {"type": "input_audio_buffer.append", "audio": data["audio"]}


def normalize_event(data: dict) -> dict | None:
    kind = data.get("type", "")
    item = str(data.get("item_id") or data.get("response_id") or "")
    if kind == "conversation.item.input_audio_transcription.delta":
        return {"type": "transcript.delta", "itemId": item, "delta": data.get("delta", "")}
    if kind == "conversation.item.input_audio_transcription.completed":
        return {"type": "transcript.done", "itemId": item, "text": data.get("transcript", "")}
    if kind in {"response.text.delta", "response.audio_transcript.delta"}:
        return {"type": "translation.delta", "itemId": item, "delta": data.get("delta", "")}
    if kind in {"response.text.done", "response.audio_transcript.done"}:
        return {"type": "translation.done", "itemId": item, "text": data.get("text", data.get("transcript", ""))}
    if kind == "response.audio.delta":
        return {"type": "audio.delta", "delta": data.get("delta", ""), "sampleRate": 24000}
    if kind == "response.done":
        response = data.get("response") or {}
        if response.get("status") in {"failed", "incomplete", "cancelled"}:
            raise ValueError("百炼翻译响应未完整完成")
        return {"type": "usage", "usage": response.get("usage") or {}}
    if kind == "session.finished":
        return {"type": "session.finished"}
    if kind == "error" or kind.endswith("transcription.failed"):
        error = data.get("error") or {}
        raise ValueError(f"百炼 {error.get('code', 'error')}: {str(error.get('message', '翻译失败'))[:400]}")
    return None


async def relay(browser: WebSocket, upstream, request: RealtimeRequest):
    async def send_audio():
        sent = 0
        finishing = False
        while True:
            raw = await asyncio.wait_for(browser.receive_text(), timeout=60)
            if finishing:
                raise ValueError("会话已结束输入，不再接受音频；请等待最终结果")
            message = audio_message(raw)
            if message["type"] == "input_audio_buffer.append":
                sent += len(base64.b64decode(message["audio"]))
                if sent > MAX_SECONDS * 16000 * 2:
                    raise ValueError("会话输入音频超过 10 分钟限制")
            await upstream.send(json.dumps(message))
            if message["type"] == "session.finish":
                # Keep watching the browser for disconnects while final results are drained.
                finishing = True

    async def receive_results():
        while True:
            data = json.loads(await asyncio.wait_for(upstream.recv(), timeout=60))
            event = normalize_event(data)
            if event:
                await browser.send_json(event)
                if event["type"] == "session.finished":
                    return

    sender = asyncio.create_task(send_audio())
    receiver = asyncio.create_task(receive_results())
    try:
        async with asyncio.timeout(MAX_SECONDS + 60):
            done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    finally:
        for task in (sender, receiver):
            task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)


async def mock_session(browser: WebSocket):
    await browser.send_json({"type": "session.ready", "mock": True, "inputSampleRate": 16000, "outputSampleRate": 24000})
    async with asyncio.timeout(MAX_SECONDS):
        while True:
            data = audio_message(await asyncio.wait_for(browser.receive_text(), timeout=60))
            if data["type"] == "session.finish":
                await browser.send_json({"type": "translation.done", "itemId": "mock",
                                         "text": "[mock] 模拟链路已结束，未识别或翻译麦克风语音。"})
                await browser.send_json({"type": "session.finished"})
                return


@router.websocket("/realtime/ws")
async def realtime_ws(browser: WebSocket):
    # Only the platform bridge can connect; browser uses its one-use ticket, never a vendor key.
    try:
        require_internal(browser.headers.get("x-internal-token", ""))
    except HTTPException:
        await browser.close(code=1008)
        return
    await browser.accept()
    try:
        raw = await asyncio.wait_for(browser.receive_text(), timeout=10)
        if len(raw) > MAX_MESSAGE:
            raise ValueError("连接消息过大")
        hello = json.loads(raw)
        token = hello.get("ticket", "") if isinstance(hello, dict) and hello.get("type") == "connect" else ""
        entry = consume_ticket(token) if isinstance(token, str) else None
    except (ValueError, WebSocketDisconnect, TimeoutError):
        await browser.close(code=1008)
        return
    if not entry or sum(_ACTIVE.values()) >= get_settings().max_concurrency or _ACTIVE.get(entry.request.user_id, 0) >= 2:
        await browser.close(code=1008)
        return
    user = entry.request.user_id
    _ACTIVE[user] = _ACTIVE.get(user, 0) + 1
    try:
        if entry.mock:
            await mock_session(browser)
        else:
            uri = entry.origin.replace("https://", "wss://", 1) + "/api-ws/v1/realtime?model=" + entry.request.model
            async with connect(uri, additional_headers={"Authorization": "Bearer " + entry.key},
                               open_timeout=15, close_timeout=5, max_size=2 * 1024 * 1024,
                               max_queue=8, compression=None) as upstream:
                created = json.loads(await asyncio.wait_for(upstream.recv(), 20))
                normalize_event(created)
                if created.get("type") != "session.created":
                    raise ValueError("百炼未返回 session.created")
                await upstream.send(json.dumps(session_update(entry.request)))
                async with asyncio.timeout(20):
                    while True:
                        updated = json.loads(await upstream.recv())
                        normalize_event(updated)
                        if updated.get("type") == "session.updated":
                            break
                await browser.send_json({"type": "session.ready", "mock": False,
                                         "inputSampleRate": 16000, "outputSampleRate": 24000})
                await relay(browser, upstream, entry.request)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - surface protocol/network failures, never vendor credentials
        message = str(exc).replace(entry.key, "[REDACTED]") if entry.key else str(exc)
        try:
            await browser.send_json({"type": "error", "message": message[:500] or "翻译超时或连接中断"})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        _ACTIVE[user] -= 1
        if not _ACTIVE[user]:
            _ACTIVE.pop(user, None)
        try:
            await browser.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
