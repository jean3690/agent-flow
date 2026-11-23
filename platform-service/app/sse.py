from __future__ import annotations

from collections.abc import Iterable, Iterator


class SseLimitError(Exception):
    pass


def iter_events(lines: Iterable[str], max_event_chars: int) -> Iterator[tuple[str, str]]:
    """Parse SSE lines into (event, data) pairs with a per-event size guard."""

    event: str | None = None
    data: list[str] = []
    event_chars = 0
    first_line = True
    for raw in lines:
        line = raw
        if first_line:
            line = line.removeprefix("﻿")
            first_line = False
        if line == "":
            if event is not None or data:
                yield event or "message", "\n".join(data)
            event = None
            data = []
            event_chars = 0
            continue
        if line.startswith(":"):
            continue
        event_chars += len(line)
        if event_chars > max_event_chars:
            raise SseLimitError("SSE 事件超过大小限制")
        if ":" in line:
            field, value = line.split(":", 1)
            value = value.removeprefix(" ")
        else:
            field, value = line, ""
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)
    if event is not None or data:
        yield event or "message", "\n".join(data)
