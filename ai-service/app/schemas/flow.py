from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NodePosition(BaseModel):
    x: float = 0
    y: float = 0


class FlowNode(BaseModel):
    id: str
    type: str
    name: str = ""
    position: NodePosition = Field(default_factory=NodePosition)
    config: dict[str, Any] = Field(default_factory=dict)


class FlowEdge(BaseModel):
    id: str | None = None
    source: str
    target: str
    source_handle: str | None = Field(default=None, alias="sourceHandle")

    model_config = {"populate_by_name": True}


class Flow(BaseModel):
    id: str | None = None
    name: str = "untitled"
    engine_type: str = Field(default="langgraph", alias="engineType")
    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def node(self, node_id: str) -> FlowNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def outgoing(self, node_id: str) -> list[FlowEdge]:
        return [e for e in self.edges if e.source == node_id]

    def incoming(self, node_id: str) -> list[FlowEdge]:
        return [e for e in self.edges if e.target == node_id]
