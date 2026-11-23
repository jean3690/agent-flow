from __future__ import annotations

import asyncio
import json
import re

import websockets
from fastapi import APIRouter, Request, WebSocket

from app.ai_client import get_ai
from app.database import session_scope
from app.errors import BizError
from app.http import current_user
from app.serialization import ok
from app.services.providers import ProviderService

router = APIRouter(prefix="/api/translations", tags=["translations"])
providers = ProviderService()
TICKET_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
LANG_PATTERN = re.compile(r"[a-z]{2,3}(-[a-z]{2,4})?")
ERROR_FRAME = json.dumps(
    {"type": "error", "message": "实时翻译连接失败，请重新开始或检查服务状态"}, ensure_ascii=False
)


@router.post("/realtime/sessions")
def create_session(request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    provider = str(payload.get("provider") or "qwen")
    if provider not in {"qwen", "mock"}:
        raise BizError("provider 必须为 qwen 或 mock")
    target = str(payload.get("targetLang") or "en")
    if not LANG_PATTERN.fullmatch(target):
        raise BizError("targetLang 格式不合法")
    voice = str(payload.get("voice") or "Tina")
    if not voice.strip() or len(voice) > 80:
        raise BizError("voice 不能为空且不能超过 80 字符")
    api_host = str(payload.get("apiHost") or "")
    if len(api_host) > 255:
        raise BizError("apiHost 不能超过 255 字符")

    body = {
        "provider": provider,
        "model": "qwen3.8-livetranslate-flash-realtime",
        "userId": user.id,
        "targetLang": target,
        "apiHost": api_host,
        "voice": voice,
        "outputAudio": bool(payload.get("outputAudio", True)),
    }
    if provider == "qwen":
        with session_scope() as session:
            credentials = providers.credentials(session, "qwen")
        if credentials:
            body.update(credentials)
    return ok((get_ai().post_json("/v1/translations/realtime/sessions", body) or {}).get("data"))


@router.websocket("/realtime/ws")
async def realtime_proxy(ws: WebSocket):
    await ws.accept()
    connection = None
    try:
        try:
            first = await asyncio.wait_for(ws.receive_text(), timeout=10)
        except Exception:  # noqa: BLE001
            await ws.close(code=1008)
            return
        try:
            hello = json.loads(first)
        except ValueError:
            hello = {}
        ticket = str(hello.get("ticket") or "") if isinstance(hello, dict) else ""
        if not isinstance(hello, dict) or hello.get("type") != "connect" or not TICKET_PATTERN.fullmatch(ticket):
            await _fail(ws)
            return
        ai = get_ai()
        try:
            connection = await asyncio.wait_for(
                websockets.connect(
                    ai.realtime_ws_url(),
                    additional_headers={"X-Internal-Token": ai.token},
                    max_size=2 * 1024 * 1024,
                    open_timeout=10,
                    close_timeout=5,
                ),
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            await _fail(ws)
            return
        await connection.send(first)

        async def client_to_upstream():
            while True:
                message = await ws.receive_text()
                if len(message) > 64 * 1024:
                    raise RuntimeError("message too large")
                await connection.send(message)

        async def upstream_to_client():
            async for message in connection:
                await ws.send_text(message if isinstance(message, str) else message.decode("utf-8"))

        tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            error = task.exception()
            if error is not None:
                raise error
        await ws.close(code=1000)
    except Exception:  # noqa: BLE001
        await _fail(ws)
    finally:
        if connection is not None:
            try:
                await connection.close()
            except Exception:  # noqa: BLE001, S110
                pass


async def _fail(ws: WebSocket) -> None:
    try:
        await ws.send_text(ERROR_FRAME)
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        await ws.close(code=1008)
    except Exception:  # noqa: BLE001, S110
        pass
