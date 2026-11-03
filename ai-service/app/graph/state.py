from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_outputs(left: dict[str, dict] | None, right: dict[str, dict] | None) -> dict[str, dict]:
    return {**(left or {}), **(right or {})}


class FlowState(TypedDict, total=False):
    input: dict[str, Any]
    variables: dict[str, Any]
    outputs: Annotated[dict[str, dict[str, Any]], merge_outputs]
    executed: Annotated[list[str], operator.add]
