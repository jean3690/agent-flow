from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = object()


class EventBufferOverflow(asyncio.CancelledError):
    """Resource-limit abort, not a user cancellation; its failure event is already queued."""


@dataclass
class RunEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"


class EventBus:
    """Bounded single-consumer buffer; synchronous producers fail rather than silently lose tokens."""

    def __init__(self, *, max_events: int = 256, max_buffer_bytes: int = 4_194_304,
                 max_event_bytes: int = 1_048_576, heartbeat_seconds: float = 15) -> None:
        if max_events < 1 or min(max_buffer_bytes, max_event_bytes) < 256 or heartbeat_seconds <= 0:
            raise ValueError("Event buffer limits must be positive (byte limits >= 256)")
        # Two terminal events + one sentinel have dedicated slots, even when normal traffic is full.
        self._queue: asyncio.Queue[tuple[str, int, bool] | object] = asyncio.Queue(maxsize=max_events + 3)
        self._max_events = max_events
        self._max_buffer_bytes = max_buffer_bytes
        self._max_event_bytes = max_event_bytes
        self._heartbeat_seconds = heartbeat_seconds
        self._normal_events = 0
        self._normal_bytes = 0
        self._buffered_bytes = 0
        self._terminal_sent = False
        self._done_sent = False
        self._run_id: str | None = None
        self._started = time.perf_counter()
        self._closed = False

    def emit(self, event: str, **data: Any) -> None:
        if self._closed or self._done_sent or (self._terminal_sent and event != "done"):
            return
        if data.get("runId") is not None:
            self._run_id = str(data["runId"])[:64]
        # done is a protocol marker, not an arbitrary data event; its reserved slot stays small.
        chunk = RunEvent(event, {} if event == "done" else data).to_sse()
        size = len(chunk.encode("utf-8"))
        if size > self._max_event_bytes:
            self._abort("EVENT_TOO_LARGE", "执行事件超过大小限制")
        terminal = event in {"run_finished", "run_failed", "done"}
        if not terminal and (self._normal_events >= self._max_events
                             or self._normal_bytes + size > self._max_buffer_bytes):
            self._abort("EVENT_BUFFER_OVERFLOW", "执行事件缓冲区已满，消费过慢，执行已停止")
        self._enqueue(chunk, size, normal=not terminal)
        if event in {"run_finished", "run_failed"}:
            self._terminal_sent = True
        elif event == "done":
            self._done_sent = True

    def _enqueue(self, chunk: str, size: int, *, normal: bool) -> None:
        self._queue.put_nowait((chunk, size, normal))
        self._buffered_bytes += size
        if normal:
            self._normal_events += 1
            self._normal_bytes += size

    def _abort(self, code: str, message: str) -> None:
        # Preserve accepted progress and append a failure, rather than discard tokens or publish success.
        failure = RunEvent("run_failed", {
            "runId": self._run_id, "status": "failed",
            "elapsedMs": int((time.perf_counter() - self._started) * 1000),
            "error": {"code": code, "message": message},
        }).to_sse()
        self._enqueue(failure, len(failure.encode("utf-8")), normal=False)
        done = RunEvent("done").to_sse()
        self._enqueue(done, len(done.encode("utf-8")), normal=False)
        self._terminal_sent = self._done_sent = True
        self.close()
        # Bypass node retry/onError=continue handlers so resource exhaustion cannot resume side effects.
        raise EventBufferOverflow(message)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(_SENTINEL)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def buffered_bytes(self) -> int:
        return self._buffered_bytes

    @property
    def buffered_events(self) -> int:
        return self._normal_events

    async def drain(self):
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=self._heartbeat_seconds)
            except asyncio.TimeoutError:
                # Comments do not occupy buffer capacity or change the execution deadline.
                yield ": keep-alive\n\n"
                continue
            if item is _SENTINEL:
                break
            chunk, size, normal = item
            self._buffered_bytes -= size
            if normal:
                self._normal_bytes -= size
                self._normal_events -= 1
            yield chunk
