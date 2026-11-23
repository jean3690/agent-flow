from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from starlette.datastructures import Headers

from app.database import session_scope
from app.security import CurrentUser, parse_token
from app.serialization import dumps
from app.services.api_keys import authenticate as authenticate_api_key

log = logging.getLogger("agentflow.http")

PUBLIC_PATHS = {
    "/api/auth/login",
    "/api/system/health",
    "/api/system/ai-health",
    "/api/translations/realtime/ws",
}


class PlatformMiddleware:
    """Authentication plus JSON body capture for /api requests."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state: dict[str, Any] = scope.setdefault("state", {})
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        headers = Headers(scope=scope)

        needs_auth = (
            path.startswith("/api") and method.upper() != "OPTIONS" and path not in PUBLIC_PATHS
        )
        is_webhook = method.upper() == "POST" and path.startswith("/api/triggers/webhook/")
        if needs_auth and not is_webhook:
            user = await asyncio.to_thread(self._resolve_user, headers)
            if user is None:
                await _send_unauthorized(send, "未登录或 token 缺失")
                return
            state["user"] = user

        body_bytes, replay = await _read_body_if_json(scope, headers, receive)
        if body_bytes is not None:
            if body_bytes:
                try:
                    state["body"] = json.loads(body_bytes.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    state["body"] = {}
            else:
                state["body"] = {}
        await self.app(scope, replay or receive, send)

    @staticmethod
    def _resolve_user(headers: Headers) -> CurrentUser | None:
        api_key = headers.get("x-api-key")
        if api_key and api_key.strip():
            try:
                with session_scope() as session:
                    user = authenticate_api_key(session, api_key)
                return user
            except Exception as exc:  # noqa: BLE001
                log.warning("api key authentication failed: %s", exc)
                return None
        authorization = headers.get("authorization") or ""
        if not authorization.startswith("Bearer "):
            return None
        try:
            return parse_token(authorization[len("Bearer ") :])
        except Exception:  # noqa: BLE001
            return None


async def _read_body_if_json(scope, headers: Headers, receive):  # type: ignore[no-untyped-def]
    method = scope.get("method", "").upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None, None
    content_type = (headers.get("content-type") or "").lower()
    if "application/json" not in content_type:
        return None, None
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return b"", None
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = b"".join(chunks)
    sent = False

    async def replay():  # type: ignore[no-untyped-def]
        nonlocal sent
        if sent:
            # Delegate afterwards so StreamingResponse can observe http.disconnect.
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return body, replay


async def _send_unauthorized(send, message: str) -> None:  # type: ignore[no-untyped-def]
    payload = dumps({"code": 4010, "message": message, "data": None}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})
