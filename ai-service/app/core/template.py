"""{{expression}} template rendering shared by prompt / url / body fields."""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.expression import evaluate

_PATTERN = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def build_names(input_data: dict[str, Any], variables: dict[str, Any], outputs: dict[str, dict]) -> dict[str, Any]:
    names: dict[str, Any] = {
        "outputs": outputs,
        "vars": variables,
        "state": {"outputs": outputs, "vars": variables, "input": input_data},
        "input": input_data,
    }
    names.update(input_data or {})
    for node_id, result in outputs.items():
        if isinstance(result, dict) and "value" in result:
            names[node_id] = result["value"]
        else:
            names[node_id] = result
    return names


def render(text: str, names: dict[str, Any], *, strict: bool = False) -> str:
    if not text:
        return ""

    def _replace(match: re.Match[str]) -> str:
        expression = match.group(1)
        try:
            return stringify(evaluate(expression, names))
        except Exception as exc:  # noqa: BLE001 - template must never crash the run
            if strict:
                raise
            return f"[{expression}: {exc}]"

    return _PATTERN.sub(_replace, text)


def render_value(text: str, names: dict[str, Any]) -> Any:
    """If the whole string is a single placeholder, keep the native type."""
    stripped = (text or "").strip()
    match = _PATTERN.fullmatch(stripped)
    if match:
        return evaluate(match.group(1), names)
    return render(text, names)
