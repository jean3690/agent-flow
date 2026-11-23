from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable

_LOCK = threading.Lock()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}


def inc(name: str, amount: float = 1, **labels: str) -> None:
    key = (name, tuple(sorted(labels.items())))
    with _LOCK:
        _COUNTERS[key] += amount


def gauge(name: str, value: float, **labels: str) -> None:
    key = (name, tuple(sorted(labels.items())))
    with _LOCK:
        _GAUGES[key] = value


def _render_samples(prefix: str, name: str, samples: Iterable[tuple[tuple[tuple[str, str], ...], float]]) -> list[str]:
    lines: list[str] = []
    for labels, value in samples:
        if labels:
            rendered = ",".join(f'{key}="{_escape(val)}"' for key, val in labels)
            lines.append(f"{name}{{{rendered}}} {_format(value)}")
        else:
            lines.append(f"{name} {_format(value)}")
    return lines


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


def render() -> str:
    lines: list[str] = []
    with _LOCK:
        counters = dict(_COUNTERS)
        gauges = dict(_GAUGES)
    grouped: dict[str, list[tuple[tuple[tuple[str, str], ...], float]]] = defaultdict(list)
    for (name, labels), value in counters.items():
        grouped[name].append((labels, value))
    for (name, labels), value in gauges.items():
        grouped[name].append((labels, value))
    for name in sorted(grouped):
        metric_type = "counter" if any(key[0] == name for key in counters) else "gauge"
        lines.append(f"# TYPE {name} {metric_type}")
        lines.extend(_render_samples(metric_type, name, grouped[name]))
    return "\n".join(lines) + "\n"
