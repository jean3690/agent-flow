from __future__ import annotations

import asyncio
import time
from typing import Any

from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.output_fields import apply_output_fields
from app.graph.state import FlowState
from app.nodes.registry import get_executor
from app.schemas.flow import FlowNode


def _int_option(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


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

    config = node.config or {}
    retry = _int_option(config.get("retry"), 0, 0, 5)
    retry_delay = _int_option(config.get("retryDelayMs"), 500, 0, 30_000)
    timeout_ms = _int_option(config.get("timeoutMs"), 0, 0, 3_600_000)
    on_error = str(config.get("onError") or "fail").strip().lower()
    attempts = retry + 1

    for attempt in range(1, attempts + 1):
        try:
            executor = get_executor(node.type)
            if timeout_ms > 0:
                output = await asyncio.wait_for(
                    executor.execute(node, state, ctx), timeout=timeout_ms / 1000
                )
            else:
                output = await executor.execute(node, state, ctx)
            output = apply_output_fields(node, output)
            elapsed = int((time.perf_counter() - started) * 1000)
            ctx.executed.append(node.id)
            ctx.emit("node_finished", nodeId=node.id, status="success", output=output, elapsedMs=elapsed)
            return {"outputs": {node.id: output}, "executed": [node.id]}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize node errors and apply retry policy
            if attempt < attempts:
                ctx.emit(
                    "node_log",
                    nodeId=node.id,
                    level="warn",
                    message=f"第 {attempt} 次执行失败，{retry_delay}ms 后重试：{exc}",
                )
                if retry_delay:
                    await asyncio.sleep(retry_delay / 1000)
                continue

            elapsed = int((time.perf_counter() - started) * 1000)
            if isinstance(exc, NodeExecutionError):
                code, message = exc.code, exc.message
            elif isinstance(exc, asyncio.TimeoutError):
                code, message = "NODE_TIMEOUT", f"节点执行超时（{timeout_ms}ms）"
            else:
                code, message = "NODE_FAILED", str(exc)

            ctx.emit(
                "node_failed",
                nodeId=node.id,
                status="failed",
                error={"code": code, "message": message},
                elapsedMs=elapsed,
            )
            if on_error in {"continue", "ignore", "skip"}:
                output = {
                    "failed": True,
                    "error": {"code": code, "message": message},
                }
                ctx.executed.append(node.id)
                ctx.emit(
                    "node_log",
                    nodeId=node.id,
                    level="warn",
                    message=f"已按 onError=continue 跳过失败，继续执行下游：{message}",
                )
                return {"outputs": {node.id: output}, "executed": [node.id]}
            if isinstance(exc, NodeExecutionError):
                raise
            raise NodeExecutionError(node.id, message) from exc

    raise NodeExecutionError(node.id, "节点执行失败")
