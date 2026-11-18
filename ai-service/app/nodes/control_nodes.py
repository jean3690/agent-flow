"""Control-flow nodes: delay / merge / subflow / foreach."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.core.errors import NodeExecutionError
from app.core.template import build_names, render_value, stringify
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.graph.subflow import pick_output, run_subflow
from app.nodes.base import NodeExecutor, extract_value
from app.nodes.registry import register
from app.schemas.flow import Flow, FlowNode


def _names(state: FlowState) -> dict[str, Any]:
    return build_names(
        state.get("input") or {},
        state.get("variables") or {},
        state.get("outputs") or {},
    )


def _render_deep(value: Any, names: dict[str, Any]) -> Any:
    """递归渲染 JSON 结构中的 {{...}}，保留数字/布尔/数组等原生类型。"""
    if isinstance(value, dict):
        return {key: _render_deep(item, names) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_deep(item, names) for item in value]
    if isinstance(value, str):
        return render_value(value, names)
    return value


def _resolve_flow(ctx: NodeContext, workflow_id: Any) -> tuple[str, Flow]:
    key = str(workflow_id or "").strip()
    if not key:
        raise NodeExecutionError("subflow", "未配置子工作流 ID")
    flow = ctx.subflows.get(key)
    if flow is None:
        raise NodeExecutionError(
            "subflow",
            f"子工作流 {key} 未加载：请确认工作流存在且已被保存",
        )
    return key, flow


def _input_config(config: dict[str, Any]) -> Any:
    raw = config.get("input")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise NodeExecutionError("subflow", f"子工作流 input 不是合法 JSON: {exc}") from exc
    return raw


@register
class DelayNodeExecutor(NodeExecutor):
    type = "delay"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        try:
            duration = int(config.get("durationMs") or config.get("duration_ms") or 1000)
        except (TypeError, ValueError):
            duration = 1000
        duration = max(0, min(duration, 600_000))

        started = time.perf_counter()
        await asyncio.sleep(duration / 1000)
        elapsed = int((time.perf_counter() - started) * 1000)
        ctx.emit("node_log", nodeId=node.id, level="info", message=f"延迟 {duration}ms 完成")
        return {"durationMs": duration, "elapsedMs": elapsed, "value": elapsed, "text": str(elapsed)}


@register
class MergeNodeExecutor(NodeExecutor):
    """把多个上游节点的输出合并为一个值，作为并行分支的汇合点。"""

    type = "merge"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        sources = config.get("sources")
        if isinstance(sources, str):
            sources = [item.strip() for item in sources.split(",") if item.strip()]
        if not sources:
            sources = [edge.source for edge in ctx.flow.incoming(node.id)]
        if not sources:
            raise NodeExecutionError(node.id, "合并节点没有可用的上游节点")

        outputs = state.get("outputs") or {}
        present = [str(source) for source in sources if str(source) in outputs]
        if not present:
            raise NodeExecutionError(node.id, "合并节点的上游节点尚未产生输出")

        mode = str(config.get("mode") or "object").lower()
        if mode in {"array", "list"}:
            value = [extract_value(outputs[source]) for source in present]
        elif mode in {"text", "join"}:
            joiner = str(config.get("joinWith") if config.get("joinWith") is not None else "\n")
            value = joiner.join(
                stringify(extract_value(outputs[source])) for source in present
            )
        elif mode == "first":
            value = next(
                (
                    extract_value(outputs[source])
                    for source in present
                    if stringify(extract_value(outputs[source])).strip()
                ),
                "",
            )
        else:
            value = {source: extract_value(outputs[source]) for source in present}

        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        return {
            "value": value,
            "text": text,
            "count": len(present),
            "sources": present,
            "outputs": {source: extract_value(outputs[source]) for source in present},
        }


@register
class SubflowNodeExecutor(NodeExecutor):
    type = "subflow"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = _names(state)
        workflow_id, flow = _resolve_flow(ctx, config.get("workflowId") or config.get("workflow_id"))

        raw_input = _input_config(config)
        if raw_input is None or raw_input == {}:
            input_data = _render_deep(dict(state.get("input") or {}), names)
        else:
            input_data = _render_deep(raw_input, names)

        try:
            timeout_ms = int(config.get("childTimeoutMs") or 0)
        except (TypeError, ValueError):
            timeout_ms = 0

        child_state, elapsed = await run_subflow(flow, input_data, ctx, timeout_ms=timeout_ms or None)
        output = pick_output(flow, child_state)
        return {
            "value": output,
            "output": output,
            "text": stringify(output),
            "outputs": child_state.get("outputs") or {},
            "nodeCount": len(flow.nodes),
            "subflowId": workflow_id,
            "elapsedMs": elapsed,
        }


@register
class ForeachNodeExecutor(NodeExecutor):
    """对数组逐项执行同一条子工作流，可限制并发数。"""

    type = "foreach"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = _names(state)

        raw_items = config.get("items")
        if raw_items is None:
            raise NodeExecutionError(node.id, "循环节点缺少 items（数组或模板表达式）")
        items = _render_deep(raw_items, names)
        if isinstance(items, str):
            try:
                parsed = json.loads(items)
                if isinstance(parsed, list):
                    items = parsed
            except json.JSONDecodeError:
                pass
        if not isinstance(items, list):
            raise NodeExecutionError(node.id, "循环节点的 items 必须是数组")

        workflow_id, flow = _resolve_flow(
            ctx, config.get("bodyWorkflowId") or config.get("body_workflow_id") or config.get("workflowId")
        )

        try:
            concurrency = max(1, min(int(config.get("concurrency") or 1), 5))
        except (TypeError, ValueError):
            concurrency = 1
        try:
            item_timeout = int(config.get("itemTimeoutMs") or 0)
        except (TypeError, ValueError):
            item_timeout = 0

        item_key = str(config.get("itemKey") or "item")
        template_input = _input_config(config)
        semaphore = asyncio.Semaphore(concurrency)

        async def _run_one(index: int, item: Any) -> dict[str, Any]:
            child_names = {**names, item_key: item, "index": index, "total": len(items)}
            if template_input:
                child_input = _render_deep(template_input, child_names)
            else:
                child_input = {item_key: item, "index": index, "total": len(items)}
            async with semaphore:
                started = time.perf_counter()
                try:
                    child_state, _ = await run_subflow(
                        flow, child_input, ctx, timeout_ms=item_timeout or None
                    )
                    return {
                        "index": index,
                        "ok": True,
                        "output": pick_output(flow, child_state),
                        "outputs": child_state.get("outputs") or {},
                        "elapsedMs": int((time.perf_counter() - started) * 1000),
                    }
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - 单项失败不影响其他项
                    return {
                        "index": index,
                        "ok": False,
                        "error": str(exc),
                        "elapsedMs": int((time.perf_counter() - started) * 1000),
                    }

        results = list(await asyncio.gather(*[_run_one(i, item) for i, item in enumerate(items)]))
        success = sum(1 for item in results if item["ok"])
        text = json.dumps(results, ensure_ascii=False, default=str)
        return {
            "results": results,
            "count": len(results),
            "successCount": success,
            "failedCount": len(results) - success,
            "subflowId": workflow_id,
            "text": text,
            "value": results,
        }
