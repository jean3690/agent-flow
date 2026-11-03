from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = object()


@dataclass
class RunEvent:
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_sse(self) -> str:
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.event}\ndata: {payload}\n\n"


class EventBus:
    """Single-consumer async queue bridging graph execution and the SSE response."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RunEvent | object] = asyncio.Queue()
        self._closed = False

    def emit(self, event: str, **data: Any) -> None:
        if self._closed:
            return
        self._queue.put_nowait(RunEvent(event, data))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(_SENTINEL)

    @property
    def closed(self) -> bool:
        return self._closed

    async def drain(self):
        while True:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            assert isinstance(item, RunEvent)
            yield item.to_sse()
