from __future__ import annotations

from app.core.errors import FlowValidationError
from app.nodes.base import NodeExecutor

_EXECUTORS: dict[str, NodeExecutor] = {}


def register(executor_cls: type[NodeExecutor]) -> type[NodeExecutor]:
    instance = executor_cls()
    _EXECUTORS[executor_cls.type] = instance
    return executor_cls


def get_executor(node_type: str) -> NodeExecutor:
    executor = _EXECUTORS.get(node_type)
    if not executor:
        raise FlowValidationError(
            f"未知节点类型: {node_type}，支持: {', '.join(sorted(_EXECUTORS))}",
            code="NODE_TYPE_UNKNOWN",
        )
    return executor


def registered_types() -> list[str]:
    return sorted(_EXECUTORS)
