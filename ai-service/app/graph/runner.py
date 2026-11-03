from __future__ import annotations

import asyncio
import time
import uuid

from app.config import Settings
from app.core.errors import AgentFlowError
from app.core.events import EventBus
from app.graph.compiler import build_graph
from app.graph.context import NodeContext
from app.nodes.base import extract_value
from app.schemas.execution import ExecutionRequest


class WorkflowRunner:
    def __init__(self, request: ExecutionRequest, bus: EventBus, settings: Settings):
        self.request = request
        self.bus = bus
        self.settings = settings
        self.run_id = request.run_id or uuid.uuid4().hex
        self.started = time.perf_counter()

    async def run(self) -> None:
        flow = self.request.flow
        ctx = NodeContext(
            run_id=self.run_id,
            settings=self.settings,
            flow=flow,
            bus=self.bus,
            providers=self.request.providers,
            resume_cache=self.request.resume,
        )
        try:
            self.bus.emit(
                "run_started",
                runId=self.run_id,
                workflowId=self.request.workflow_id,
                startedAt=int(time.time() * 1000),
                nodeCount=len(flow.nodes),
            )
            graph = build_graph(flow, ctx)
            timeout_s = max(1.0, (self.request.options.timeout_ms or 120_000) / 1000)
            final_state = await asyncio.wait_for(
                graph.ainvoke(
                    {
                        "input": self.request.input,
                        "variables": {},
                        "outputs": {},
                        "executed": [],
                    },
                    config={"recursion_limit": max(25, len(flow.nodes) * 4)},
                ),
                timeout=timeout_s,
            )
            elapsed = int((time.perf_counter() - self.started) * 1000)
            output = _pick_output(flow, final_state)
            self.bus.emit(
                "run_finished",
                runId=self.run_id,
                status="success",
                output=output,
                outputs=final_state.get("outputs") or {},
                elapsedMs=elapsed,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.perf_counter() - self.started) * 1000)
            self.bus.emit(
                "run_failed",
                runId=self.run_id,
                status="failed",
                error={"code": "RUN_TIMEOUT", "message": "执行超时"},
                elapsedMs=elapsed,
            )
        except AgentFlowError as exc:
            elapsed = int((time.perf_counter() - self.started) * 1000)
            self.bus.emit(
                "run_failed",
                runId=self.run_id,
                status="failed",
                error={"code": exc.code, "message": exc.message},
                elapsedMs=elapsed,
            )
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace into SSE
            elapsed = int((time.perf_counter() - self.started) * 1000)
            self.bus.emit(
                "run_failed",
                runId=self.run_id,
                status="failed",
                error={"code": "RUN_FAILED", "message": str(exc)},
                elapsedMs=elapsed,
            )
        finally:
            self.bus.emit("done")
            self.bus.close()


def _pick_output(flow, state) -> object:
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
