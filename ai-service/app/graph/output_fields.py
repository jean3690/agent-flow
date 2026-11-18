"""User-defined output field aliases, applied once before an output is stored.

Aliases are strictly additive: original keys are never removed or overwritten,
so ``extract_value`` and existing ``{{nodeId.text}}`` templates keep working.
``hidden`` is UI-only and deliberately ignored here.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas.flow import FlowNode

# These keys drive extract_value / _pick_output; an alias must never shadow them.
_RESERVED = {"value", "text", "body", "audioUrl"}
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def apply_output_fields(node: FlowNode, output: Any) -> Any:
    spec = (node.config or {}).get("outputFields")
    if not isinstance(spec, list) or not spec or not isinstance(output, dict):
        return output

    result = dict(output)
    for entry in spec:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("key") or "").strip()
        alias = str(entry.get("alias") or "").strip()
        if not source or not alias or alias == source or source not in output:
            continue
        if alias in _RESERVED or alias.startswith("__") or alias in output:
            continue
        if not _IDENTIFIER.match(alias):
            continue
        result[alias] = output[source]
    return result
