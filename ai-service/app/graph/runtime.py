from __future__ import annotations

import time
from typing import Any

from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.registry import get_executor
from app.schemas.flow import FlowNode


async def execute_node(node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
    seq = ctx.next_seq()
    started = time.perf_counter()
    ctx.emit(
        "node_started",
        nodeId=node.id,
        nodeType=node.type,
        nodeName=node.name or node.type,
        seq=seq,
        timestamp=int(time.time() * 1000),
    )

    cached = ctx.resume_cache.get(node.id)
    if isinstance(cached, dict) and cached:
        # 断点续跑：命中缓存直接复用上次输出，不再真正执行
        ctx.emit("node_log", nodeId=node.id, level="info", message="复用上次执行结果（断点续跑）")
        ctx.executed.append(node.id)
        ctx.emit("node_finished", nodeId=node.id, status="success", output=cached, elapsedMs=0)
        return {"outputs": {node.id: cached}, "executed": [node.id]}

    try:
        executor = get_executor(node.type)
        output = await executor.execute(node, state, ctx)
        elapsed = int((time.perf_counter() - started) * 1000)
        ctx.executed.append(node.id)
        ctx.emit("node_finished", nodeId=node.id, status="success", output=output, elapsedMs=elapsed)
        return {"outputs": {node.id: output}, "executed": [node.id]}
    except NodeExecutionError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        ctx.emit(
            "node_failed",
            nodeId=node.id,
            status="failed",
            error={"code": exc.code, "message": exc.message},
            elapsedMs=elapsed,
        )
        raise
    except Exception as exc:  # noqa: BLE001 - convert any node bug into a node failure
        elapsed = int((time.perf_counter() - started) * 1000)
        ctx.emit(
            "node_failed",
            nodeId=node.id,
            status="failed",
            error={"code": "NODE_FAILED", "message": str(exc)},
            elapsedMs=elapsed,
        )
        raise NodeExecutionError(node.id, str(exc)) from exc
