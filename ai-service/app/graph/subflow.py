"""Run an embedded workflow (subflow / foreach body) inside a parent run."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import extract_value
from app.schemas.flow import Flow

MAX_SUBFLOW_DEPTH = 5


class _SilentBus:
    """子工作流不向父级 SSE 透传事件，避免节点 id 冲突；父节点只汇报自己的结果。"""

    closed = True

    def emit(self, *_: Any, **__: Any) -> None:
        return None

    def close(self) -> None:
        return None


def pick_output(flow: Flow, state: FlowState) -> Any:
    """取子工作流的最终输出：优先 output 节点，其次最后一个已执行节点的 value。"""
    outputs = state.get("outputs") or {}
    executed = state.get("executed") or []
    last_value = None
    for node_id in reversed(executed):
        node = flow.node(node_id)
        if node is None or node_id not in outputs:
            continue
        value = extract_value(outputs[node_id])
        if node.type == "output":
            return value
        if last_value is None:
            last_value = value
    return last_value


async def run_subflow(
    flow: Flow,
    input_data: dict[str, Any],
    ctx: NodeContext,
    *,
    timeout_ms: int | None = None,
) -> tuple[FlowState, int]:
    """编译并执行一条子工作流，返回最终 state 与耗时（毫秒）。"""

    if ctx.depth >= MAX_SUBFLOW_DEPTH:
        raise NodeExecutionError(
            "subflow", f"子工作流嵌套超过 {MAX_SUBFLOW_DEPTH} 层，请检查是否循环引用"
        )

    # 延迟导入：compiler -> runtime -> registry -> control_nodes -> subflow 形成环
    from app.graph.compiler import build_graph

    child_ctx = NodeContext(
        run_id=f"{ctx.run_id}-sub-{uuid.uuid4().hex[:8]}",
        settings=ctx.settings,
        flow=flow,
        bus=_SilentBus(),
        workflow_id=ctx.workflow_id,
        user_id=ctx.user_id,
        providers=ctx.providers,
        mcp_servers=ctx.mcp_servers,
        subflows=ctx.subflows,
        depth=ctx.depth + 1,
    )
    graph = build_graph(flow, child_ctx)
    started = time.perf_counter()
    coroutine = graph.ainvoke(
        {"input": input_data or {}, "variables": {}, "outputs": {}, "executed": []},
        config={"recursion_limit": max(25, len(flow.nodes) * 4)},
    )
    if timeout_ms and timeout_ms > 0:
        state = await asyncio.wait_for(coroutine, timeout=max(1, timeout_ms) / 1000)
    else:
        state = await coroutine
    elapsed = int((time.perf_counter() - started) * 1000)
    return state, elapsed
