from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings
from app.errors import BizError, not_found
from app.serialization import dumps, loads

log = logging.getLogger("agentflow.ai")


class AiClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.base_url = settings.ai_service_base_url.rstrip("/")
        self.timeout_ms = settings.ai_service_timeout_ms
        self.connect_timeout_ms = settings.ai_connect_timeout_ms
        self.token = settings.internal_token
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=self.connect_timeout_ms / 1000,
                read=self.timeout_ms / 1000,
                write=self.timeout_ms / 1000,
                pool=self.connect_timeout_ms / 1000,
            ),
            follow_redirects=False,
        )

    # ------------------------------------------------------------------ basics
    def _url(self, path: str) -> str:
        return self.base_url + (path if path.startswith("/") else "/" + path)

    def _headers(self, internal: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if internal:
            headers["X-Internal-Token"] = self.token
        return headers

    def _check(self, response: httpx.Response, action: str, detail: bool = True) -> None:
        if response.status_code < 300:
            return
        body = response.text if detail else ""
        raise BizError(f"{action}: HTTP {response.status_code} {body}".strip())

    def _json(self, response: httpx.Response, action: str) -> dict[str, Any]:
        self._check(response, action)
        try:
            return response.json()
        except ValueError as exc:
            raise BizError(f"{action}: 响应不是合法 JSON") from exc

    def get(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.get(self._url(path), headers=self._headers())
        except httpx.HTTPError as exc:
            raise BizError(f"无法连接 AI 服务: {exc}") from exc
        return self._json(response, "AI 服务返回错误")

    def post_json(self, path: str, body: Any, internal: bool = True) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._url(path),
                content=dumps(body),
                headers={**self._headers(internal), "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise BizError(f"无法连接 AI 服务: {exc}") from exc
        return self._json(response, "AI 服务返回错误")

    def post_empty(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.post(self._url(path), headers=self._headers(internal=True))
        except httpx.HTTPError as exc:
            raise BizError(f"无法连接 AI 服务: {exc}") from exc
        return self._json(response, "AI 服务返回错误")

    def put_json(self, path: str, body: Any) -> dict[str, Any]:
        try:
            response = self._client.put(
                self._url(path),
                content=dumps(body),
                headers={**self._headers(internal=True), "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise BizError(f"保存失败: {exc}") from exc
        if response.status_code >= 300:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise BizError(detail if isinstance(detail, str) else f"AI 服务拒绝保存: HTTP {response.status_code}")
        return self._json(response, "保存失败")

    def delete(self, path: str) -> dict[str, Any]:
        try:
            response = self._client.delete(self._url(path), headers=self._headers(internal=True))
        except httpx.HTTPError as exc:
            raise BizError(f"删除文件失败: {exc}") from exc
        if response.status_code == 404:
            raise not_found(f"文件不存在: {path}")
        self._check(response, "删除文件失败")
        return loads(response.text, {})

    def data(self, path: str) -> Any:
        return self.get(path).get("data")

    def data_list(self, path: str) -> list[Any]:
        value = self.data(path)
        return value if isinstance(value, list) else []

    def healthy(self) -> bool:
        try:
            return str(self.get("/health").get("status", "")).upper() == "UP"
        except Exception as exc:  # noqa: BLE001
            log.warning("ai service health check failed: %s", exc)
            return False

    # ------------------------------------------------------------- executions
    @contextmanager
    def open_execution(self, payload: str) -> Iterator[httpx.Response]:
        timeout = self.timeout_ms / 1000
        client = httpx.Client(
            timeout=httpx.Timeout(connect=self.connect_timeout_ms / 1000, read=timeout, write=timeout, pool=timeout)
        )
        try:
            with client.stream(
                "POST",
                self._url("/v1/executions"),
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "X-Internal-Token": self.token,
                },
            ) as response:
                if response.status_code >= 300:
                    raise BizError(f"AI 服务拒绝执行: HTTP {response.status_code}")
                yield response
        except httpx.HTTPError as exc:
            raise BizError(f"无法连接 AI 服务: {exc}") from exc
        finally:
            client.close()

    def cancel_execution(self, run_id: str) -> None:
        try:
            self._client.post(
                self._url(f"/v1/executions/{quote(run_id, safe='')}/cancel"),
                content="{}",
                headers={**self._headers(internal=True), "Content-Type": "application/json"},
                timeout=self.connect_timeout_ms / 1000,
            )
        except httpx.HTTPError as exc:
            log.debug("AI cancellation notification failed, runId=%s: %s", run_id, exc)

    # ------------------------------------------------------------------- files
    def _file_headers(self, owner_id: int, legacy: bool) -> dict[str, str]:
        headers = {"X-Internal-Token": self.token, "Accept": "application/json"}
        if legacy:
            headers["X-Storage-Legacy"] = "true"
        else:
            headers["X-Storage-User-Id"] = str(owner_id)
        return headers

    def file_json(self, method: str, path: str, body: Any, owner_id: int, legacy: bool) -> Any:
        try:
            response = self._client.request(
                method,
                self._url(path),
                content=None if body is None else dumps(body),
                headers={**self._file_headers(owner_id, legacy), "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise BizError(f"文件操作失败: {exc}") from exc
        if response.status_code == 404:
            raise not_found("文件不存在")
        if response.status_code >= 300:
            raise BizError(f"文件服务拒绝请求: HTTP {response.status_code}")
        return (response.json() or {}).get("data")

    def file_upload(self, name: str, content: bytes, content_type: str | None, owner_id: int) -> Any:
        query = "" if not name else "?name=" + quote(name, safe="")
        try:
            response = self._client.post(
                self._url("/v1/files" + query),
                content=content,
                headers={
                    **self._file_headers(owner_id, False),
                    "Content-Type": content_type or "application/octet-stream",
                },
            )
        except httpx.HTTPError as exc:
            raise BizError(f"上传文件失败: {exc}") from exc
        if response.status_code >= 300:
            raise BizError(f"上传文件失败: HTTP {response.status_code}")
        return (response.json() or {}).get("data")

    def upload_file(self, name: str, content: bytes, content_type: str | None) -> Any:
        query = "" if not name else "?name=" + quote(name, safe="")
        try:
            response = self._client.post(
                self._url("/v1/files" + query),
                content=content,
                headers={"Content-Type": content_type or "application/octet-stream", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise BizError(f"上传文件失败: {exc}") from exc
        self._check(response, "上传文件失败")
        return (response.json() or {}).get("data")

    def file_download(self, path: str, owner_id: int, legacy: bool) -> bytes:
        try:
            response = self._client.get(
                self._url(path),
                headers={**self._file_headers(owner_id, legacy), "Accept": "*/*"},
            )
        except httpx.HTTPError as exc:
            raise BizError(f"读取文件失败: {exc}") from exc
        if response.status_code == 404:
            raise not_found("文件不存在")
        if response.status_code >= 300:
            raise BizError(f"下载文件失败: HTTP {response.status_code}")
        return response.content

    def download(self, path: str) -> bytes:
        try:
            response = self._client.get(self._url(path))
        except httpx.HTTPError as exc:
            raise BizError(f"读取文件失败: {exc}") from exc
        if response.status_code == 404:
            raise not_found(f"文件不存在: {path}")
        self._check(response, "读取文件失败")
        return response.content

    def realtime_ws_url(self) -> str:
        base = self.base_url
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return base + "/v1/translations/realtime/ws"


_ai: AiClient | None = None


def get_ai() -> AiClient:
    global _ai
    if _ai is None:
        _ai = AiClient()
    return _ai
