from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.schemas.flow import FlowNode


class NodeExecutor(ABC):
    type: ClassVar[str] = "base"

    @abstractmethod
    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        """Run the node and return the output payload stored in state.outputs[node.id]."""


def extract_value(result: Any) -> Any:
    if isinstance(result, dict):
        for key in ("value", "text", "body", "audioUrl"):
            if key in result:
                return result[key]
        return result
    return result
