from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import metrics
from app.ai_client import AiClient, get_ai
from app.config import get_settings
from app.database import session_scope
from app.errors import BizError, conflict, not_found
from app.flow import execution_graph, fingerprint, validate
from app.models import ExecutionNodeLog, ExecutionRecord, Workflow
from app.pricing import ModelPricingService
from app.security import CurrentUser
from app.serialization import dumps, iso, loads
from app.services import workflows
from app.sse import iter_events

log = logging.getLogger("agentflow.execution")

RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"
CANCELED = "CANCELED"


class ExecutionCanceled(Exception):
    pass


class ExecutionTimeout(Exception):
    def __init__(self) -> None:
        super().__init__("执行超时（Python 平台服务连接与读取期限）")


class ExecutionControl:
    """Single execution's upstream handle: cancellation, deadline and stream release."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._canceled = False
        self._timed_out = False
        self._closed = False
        self._deadline: float | None = None
        self._response: Any = None
        self._timer: threading.Timer | None = None
        self.client_closed = False

    def start(self, timeout_ms: int) -> None:
        with self._lock:
            if self._closed or self._timer is not None:
                raise BizError("执行期限已启动或资源已释放")
            if timeout_ms < 1:
                raise BizError("timeoutMs 必须为正数")
            self.check_stopped()
            self._deadline = time.monotonic() + timeout_ms / 1000
            self._timer = threading.Timer(timeout_ms / 1000, self._on_deadline)
            self._timer.daemon = True
            self._timer.start()

    def attach(self, response: Any) -> None:
        with self._lock:
            if self._closed or self._canceled or self._timed_out:
                self._close_response(response)
                self.check_stopped()
            self._response = response

    def check_stopped(self) -> None:
        if self._deadline is not None and time.monotonic() >= self._deadline and not self._timed_out:
            self._stop_timeout()
        if self._timed_out:
            raise ExecutionTimeout()
        if self._canceled:
            raise ExecutionCanceled("已取消")

    @property
    def is_canceled(self) -> bool:
        return self._canceled

    @property
    def is_timed_out(self) -> bool:
        return self._timed_out

    def cancel(self) -> None:
        self._stop_canceled()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._timer is not None:
                self._timer.cancel()
            response = self._response
            self._response = None
        self._close_response(response)

    def _on_deadline(self) -> None:
        self._stop_timeout()

    def _stop_timeout(self) -> None:
        with self._lock:
            if self._closed or self._timed_out or self._canceled:
                return
            self._timed_out = True
            response = self._response
        self._close_response(response)

    def _stop_canceled(self) -> None:
        with self._lock:
            if self._closed or self._timed_out or self._canceled:
                return
            self._canceled = True
            response = self._response
        self._close_response(response)

    @staticmethod
    def _close_response(response: Any) -> None:
        if response is None:
            return
        try:
            response.close()
        except Exception:  # noqa: BLE001, S110 - best-effort resource release
            pass


class PoolFull(Exception):
    pass


class BoundedExecutor:
    def __init__(self, core: int, maximum: int, queue_capacity: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(core, maximum), thread_name_prefix="exec-")
        self._slots = threading.BoundedSemaphore(maximum + max(0, queue_capacity))
        self._active = 0
        self._queued = 0
        self._lock = threading.Lock()

    def submit(self, fn: Callable[[], Any]) -> Future:
        if not self._slots.acquire(blocking=False):
            raise PoolFull()
        with self._lock:
            self._queued += 1
            metrics.gauge("agentflow_execution_pool_queued", self._queued)
            metrics.gauge("agentflow_execution_pool_active", self._active)

        def wrapper() -> Any:
            with self._lock:
                self._queued -= 1
                self._active += 1
                metrics.gauge("agentflow_execution_pool_queued", self._queued)
                metrics.gauge("agentflow_execution_pool_active", self._active)
            try:
                return fn()
            finally:
                with self._lock:
                    self._active -= 1
                    metrics.gauge("agentflow_execution_pool_active", self._active)
                self._slots.release()

        return self._pool.submit(wrapper)


class ExecutionService:
    def __init__(self, ai: AiClient | None = None) -> None:
        settings = get_settings()
        self.ai = ai or get_ai()
        self.settings = settings
        self.pricing = ModelPricingService()
        self.executor = BoundedExecutor(
            settings.execution_core_pool_size,
            max(settings.execution_core_pool_size, settings.execution_max_pool_size),
            settings.execution_queue_capacity,
        )
        self._running: dict[str, ExecutionControl] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- lifecycle
    def start_stream(self, workflow_id: int, request: dict[str, Any], user: CurrentUser,
                     emit: Callable[[str, str], None]) -> tuple[ExecutionRecord, ExecutionControl]:
        with session_scope() as session:
            workflow = workflows.get_entity(session, workflow_id, user)
            prepared = self._prepare(session, workflow, request, user, prefer_published=False)
            session.add(prepared)
            session.flush()
            session.expunge(prepared)
        control = ExecutionControl()
        self._register(prepared.run_id, control)
        try:
            self.executor.submit(lambda: self._stream_worker(prepared, control, emit))
        except PoolFull:
            self._reject(prepared, control)
        return prepared, control

    def run_sync(self, workflow_id: int, request: dict[str, Any], user: CurrentUser) -> dict[str, Any]:
        with session_scope() as session:
            workflow = workflows.get_entity(session, workflow_id, user)
            record = self._prepare(session, workflow, request, user, prefer_published=False)
            payload = record._payload  # type: ignore[attr-defined]
            session.add(record)
            session.flush()
            session.expunge(record)
        control = ExecutionControl()
        self._register(record.run_id, control)
        future: Future
        try:
            future = self.executor.submit(lambda: self._run_worker(record, payload, control))
        except PoolFull:
            self._reject(record, control)
        return future.result()

    def submit(self, workflow_id: int, request: dict[str, Any], user_id: int | None,
               prefer_published: bool, on_finish: Callable[[dict[str, Any]], None] | None = None) -> str:
        with session_scope() as session:
            workflow = workflows.get_entity(session, workflow_id)
            owner = CurrentUser(user_id or workflow.user_id, None, "USER")
            record = self._prepare(session, workflow, request, owner, prefer_published)
            payload = record._payload  # type: ignore[attr-defined]
            session.add(record)
            session.flush()
            session.expunge(record)
        control = ExecutionControl()
        self._register(record.run_id, control)

        def job() -> None:
            result = self._run_worker(record, payload, control)
            if on_finish is not None:
                try:
                    on_finish(result)
                except Exception as exc:  # noqa: BLE001
                    log.warning("execution callback failed, runId=%s: %s", record.run_id, exc)

        try:
            self.executor.submit(job)
        except PoolFull:
            self._reject(record, control)
        return record.run_id

    # ------------------------------------------------------------------- cancel
    def cancel(self, session: Session, run_id: str, user: CurrentUser) -> None:
        record = self._require(session, run_id, user)
        control = self._find_control(run_id)
        if control is None:
            if record.status == RUNNING:
                record.status = CANCELED
                record.error_message = "已取消"
                record.elapsed_ms = self._elapsed_since(record)
                record.finished_at = datetime.now()
                session.flush()
            return
        control.cancel()
        try:
            self.ai.cancel_execution(run_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("cancel request to ai-service failed, runId=%s: %s", run_id, exc)

    def delete(self, session: Session, run_id: str, user: CurrentUser) -> None:
        record = self._require(session, run_id, user)
        if record.status == RUNNING or self._find_control(run_id) is not None:
            raise conflict("请先取消执行并等待结束后再删除")
        session.execute(delete(ExecutionNodeLog).where(ExecutionNodeLog.run_id == run_id))
        session.delete(record)

    def page(self, session: Session, current: int, size: int, workflow_id: int | None,
             status: str | None, user: CurrentUser) -> dict[str, Any]:
        if workflow_id is not None:
            workflows.get_entity(session, workflow_id, user)
        current = max(1, current)
        size = max(1, size)
        conditions = [ExecutionRecord.deleted == 0]
        if not user.is_admin:
            conditions.append(ExecutionRecord.user_id == user.id)
        if workflow_id is not None:
            conditions.append(ExecutionRecord.workflow_id == workflow_id)
        if status and status.strip():
            conditions.append(ExecutionRecord.status == status.strip())
        total = session.scalar(select(func.count()).select_from(ExecutionRecord).where(*conditions)) or 0
        rows = session.scalars(
            select(ExecutionRecord)
            .where(*conditions)
            .order_by(ExecutionRecord.id.desc())
            .offset((current - 1) * size)
            .limit(size)
        ).all()
        from app.serialization import page as page_result

        return page_result([self._summary(item) for item in rows], int(total), current, size)

    def detail(self, session: Session, run_id: str, user: CurrentUser) -> dict[str, Any]:
        record = self._require(session, run_id, user)
        nodes = session.scalars(
            select(ExecutionNodeLog)
            .where(ExecutionNodeLog.run_id == run_id)
            .order_by(ExecutionNodeLog.seq.asc(), ExecutionNodeLog.id.asc())
        ).all()
        return {
            "runId": record.run_id,
            "resumeRunId": record.resume_run_id,
            "workflowId": record.workflow_id,
            "workflowName": record.workflow_name,
            "status": record.status,
            "flowVersion": record.flow_version,
            "promptTokens": record.prompt_tokens,
            "completionTokens": record.completion_tokens,
            "totalTokens": record.total_tokens,
            "costUsd": float(record.cost_usd or 0),
            "input": record.input_data,
            "output": record.output_data,
            "errorMessage": record.error_message,
            "elapsedMs": record.elapsed_ms,
            "startedAt": iso(record.started_at),
            "finishedAt": iso(record.finished_at),
            "nodes": [self._node_vo(item) for item in nodes],
        }

    def recover_stale(self) -> int:
        message = "服务重启，执行中断（未收到终态）"
        recovered = 0
        with session_scope() as session:
            stale = session.scalars(
                select(ExecutionRecord).where(
                    ExecutionRecord.status == RUNNING, ExecutionRecord.deleted == 0
                )
            ).all()
            now = datetime.now()
            for record in stale:
                record.status = FAILED
                record.error_message = message
                record.finished_at = now
                record.elapsed_ms = self._elapsed(record.started_at, now)
                nodes = session.scalars(
                    select(ExecutionNodeLog).where(
                        ExecutionNodeLog.run_id == record.run_id, ExecutionNodeLog.status == RUNNING
                    )
                ).all()
                for node in nodes:
                    node.status = FAILED
                    node.error_message = message
                    node.finished_at = now
                    node.elapsed_ms = self._elapsed(node.started_at, now)
                recovered += 1
            if recovered:
                log.warning("recovered %s stale RUNNING execution(s)", recovered)
        return recovered

    # ------------------------------------------------------------------ prepare
    def _prepare(self, session: Session, workflow: Workflow, request: dict[str, Any],
                 user: CurrentUser, prefer_published: bool) -> ExecutionRecord:
        flow, version, _published = workflows.flow_for_run(session, workflow, prefer_published)
        flow = copy.deepcopy(flow)
        validate(flow)
        timeout = request.get("timeoutMs")
        if timeout is not None and (int(timeout) < 1 or int(timeout) > 3_600_000):
            raise BizError("timeoutMs 必须在 1 到 3600000 之间")
        run_id = uuid.uuid4().hex
        record = ExecutionRecord(
            run_id=run_id,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            user_id=user.id,
            status=RUNNING,
            node_count=len(flow.get("nodes") or []),
            flow_version=version,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_usd=Decimal(0),
            elapsed_ms=0,
        )
        input_data = request.get("input") if isinstance(request.get("input"), dict) else {}
        payload: dict[str, Any] = {
            "runId": run_id,
            "workflowId": str(workflow.id),
            "userId": user.id,
            "flow": flow,
            "input": input_data,
            "providers": self._providers().credentials_for_run(session),
        }
        subflows = self._collect_subflows(session, flow, workflow.id, user)
        payload["mcpServers"] = self._mcp().for_run(
            session, [*subflows.values(), flow], user
        )
        if subflows:
            payload["subflows"] = subflows
        options: dict[str, Any] = {}
        base_timeout = 120_000 if timeout is None else int(timeout)
        approval_wait = max(
            [self._approval_timeout(item) for item in [*subflows.values(), flow]] or [0]
        )
        options["timeoutMs"] = max(base_timeout, approval_wait)
        if request.get("mock") is not None:
            options["mock"] = bool(request.get("mock"))
        payload["options"] = options
        record.execution_fingerprint = fingerprint(payload)
        resume_run_id = request.get("resumeRunId")
        if resume_run_id and str(resume_run_id).strip():
            record.resume_run_id = str(resume_run_id).strip()
            payload["resume"] = self._resume(
                session, record.resume_run_id, workflow.id, user, record.execution_fingerprint, flow
            )
        record.input_data = dumps(payload["input"])
        record.started_at = datetime.now()
        record._payload = dumps(payload)
        return record

    def _collect_subflows(self, session: Session, flow: dict[str, Any], root_id: int,
                          user: CurrentUser) -> dict[str, Any]:
        result: dict[str, Any] = {}
        visiting = {root_id}

        def walk(current: dict[str, Any], depth: int) -> None:
            if depth > 4:
                raise BizError("子工作流嵌套层级过深（最多 5 层）")
            for node in current.get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                node_type = node.get("type")
                config = node.get("config") if isinstance(node.get("config"), dict) else {}
                ids: list[int] = []
                if node_type in {"subflow", "foreach"}:
                    raw = config.get("bodyWorkflowId") if node_type == "foreach" else config.get("workflowId")
                    try:
                        value = int(raw) if raw is not None else 0
                    except (TypeError, ValueError):
                        value = 0
                    if value <= 0:
                        try:
                            value = int(config.get("workflowId") or 0)
                        except (TypeError, ValueError):
                            value = 0
                    if value > 0:
                        ids.append(value)
                elif node_type == "orchestrator":
                    ids.extend(self._worker_ids(config))
                for sub_id in ids:
                    if sub_id in visiting:
                        raise BizError(f"子工作流存在循环引用: {sub_id}")
                    visiting.add(sub_id)
                    key = str(sub_id)
                    if key not in result:
                        if len(result) >= 20:
                            raise BizError("单次执行最多引用 20 个子工作流")
                        sub_flow = copy.deepcopy(
                            workflows.read_flow(workflows.get_entity(session, sub_id, user).flow_data)
                        )
                        validate(sub_flow)
                        result[key] = sub_flow
                        walk(sub_flow, depth + 1)
                    visiting.discard(sub_id)

        walk(flow, 0)
        return result

    def _worker_ids(self, config: dict[str, Any]) -> list[int]:
        workers = config.get("workers")
        if isinstance(workers, str):
            try:
                workers = json.loads(workers)
            except ValueError as exc:
                raise BizError("协调节点执行者配置不是合法 JSON") from exc
        ids: list[int] = []
        if isinstance(workers, list):
            for worker in workers:
                raw = worker.get("workflowId") if isinstance(worker, dict) else None
                try:
                    value = int(raw) if raw is not None else 0
                except (TypeError, ValueError):
                    value = 0
                if value > 0 and value not in ids:
                    ids.append(value)
        return ids

    @staticmethod
    def _approval_timeout(flow: dict[str, Any]) -> int:
        wait = 0
        for node in flow.get("nodes") or []:
            if not isinstance(node, dict) or node.get("type") != "human_approval":
                continue
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            try:
                seconds = int(config.get("waitSeconds", 120))
            except (TypeError, ValueError):
                seconds = 120
            wait = max(wait, min(600, max(0, seconds)))
        return 0 if wait == 0 else wait * 1000 + 30_000

    def _resume(self, session: Session, run_id: str, workflow_id: int, user: CurrentUser, fp: str,
                flow: dict[str, Any]) -> dict[str, Any]:
        source = session.scalar(
            select(ExecutionRecord).where(ExecutionRecord.run_id == run_id, ExecutionRecord.deleted == 0)
        )
        if source is None or (not user.is_admin and source.user_id != user.id):
            raise not_found(f"执行记录不存在: {run_id}")
        if source.workflow_id != workflow_id:
            raise conflict("续跑记录与当前工作流不一致")
        if source.status not in {FAILED, CANCELED} or source.finished_at is None:
            raise conflict("只能续跑已结束的失败或取消记录，请等待执行完成或完整重跑")
        if not source.execution_fingerprint or not source.execution_fingerprint.strip():
            raise conflict("历史执行缺少一致性指纹，请完整重跑")
        if source.execution_fingerprint != fp:
            raise conflict("执行输入、工作流定义或运行配置已变化，请完整重跑")
        logs = session.scalars(
            select(ExecutionNodeLog)
            .where(ExecutionNodeLog.run_id == run_id)
            .order_by(ExecutionNodeLog.seq.asc(), ExecutionNodeLog.id.asc())
        ).all()
        types = {
            str(node.get("id")): str(node.get("type"))
            for node in flow.get("nodes") or []
            if isinstance(node, dict)
        }
        latest: dict[str, ExecutionNodeLog] = {}
        for item in logs:
            if types.get(item.node_id) == item.node_type:
                latest[item.node_id] = item
        graph = self._dependency_graph(flow, set(types))
        invalid = {node_id for node_id in types if latest.get(node_id) is None or latest[node_id].status != SUCCESS}
        queue = list(invalid)
        while queue:
            current = queue.pop(0)
            for descendant in graph.get(current, []):
                if descendant not in invalid:
                    invalid.add(descendant)
                    queue.append(descendant)
        cache: dict[str, Any] = {}
        for item in latest.values():
            if item.node_id in invalid or item.node_type == "input":
                continue
            try:
                output = loads(item.output_data)
            except Exception as exc:
                raise conflict("成功节点输出已损坏，无法安全续跑，请完整重跑") from exc
            if not isinstance(output, dict):
                raise conflict("成功节点输出缺失或格式不兼容，请完整重跑")
            cache[item.node_id] = output
        return cache

    def _dependency_graph(self, flow: dict[str, Any], node_ids: set[str]) -> dict[str, list[str]]:
        graph = {key: list(value) for key, value in execution_graph(flow).items()}
        import re

        pattern = re.compile(r"\{\{\s*([^\s.{}]+)")
        for node in flow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            references: set[str] = set()
            self._collect_refs(node.get("config"), references, pattern)
            if node.get("type") == "merge":
                sources = (node.get("config") or {}).get("sources")
                if isinstance(sources, str):
                    references.update(part.strip() for part in sources.split(","))
                elif isinstance(sources, list):
                    references.update(str(item) for item in sources)
            target = str(node.get("id"))
            for source in references:
                if (
                    source in node_ids
                    and source != target
                    and source in graph
                    and target not in graph[source]
                ):
                    graph[source].append(target)
        return graph

    def _collect_refs(self, config: Any, references: set[str], pattern: Any) -> None:
        if isinstance(config, str):
            references.update(pattern.findall(config))
        elif isinstance(config, dict):
            for value in config.values():
                self._collect_refs(value, references, pattern)
        elif isinstance(config, list):
            for value in config:
                self._collect_refs(value, references, pattern)

    # ------------------------------------------------------------------- worker
    def _stream_worker(self, record: ExecutionRecord, control: ExecutionControl,
                       emit: Callable[[str, str], None]) -> None:
        logs: dict[str, dict[str, Any]] = {}
        try:
            self._consume(record, control, logs, emit=emit)
        except ExecutionCanceled:
            self._fail(record, control, ExecutionCanceled("已取消"))
        except ExecutionTimeout as exc:
            self._fail(record, control, exc)
        except Exception as exc:  # noqa: BLE001
            self._fail(record, control, exc)
        finally:
            control.close()
            persisted = self._persist(record, logs, control, emit)
            event = "run_finished" if record.status == SUCCESS else "run_failed"
            upstream = getattr(record, "_terminal", None)
            if persisted and not control.is_timed_out and upstream is not None and upstream[0] == event:
                emit(event, upstream[1])
            else:
                code = (
                    "RUN_TIMEOUT"
                    if persisted and control.is_timed_out
                    else ("RUN_CANCELED" if record.status == CANCELED else "RUN_FAILED")
                )
                emit(
                    event,
                    dumps(
                        {
                            "runId": record.run_id,
                            "status": (record.status or "").lower(),
                            "elapsedMs": record.elapsed_ms,
                            "error": {"code": code, "message": record.error_message or "执行中断"},
                        }
                    ),
                )
            emit("done", "{}")
            emit("__end__", "")
            self._unregister(record.run_id, control)

    def _run_worker(self, record: ExecutionRecord, payload: str,
                    control: ExecutionControl) -> dict[str, Any]:
        logs: dict[str, dict[str, Any]] = {}
        try:
            self._consume(record, control, logs, emit=None)
        except ExecutionCanceled:
            self._fail(record, control, ExecutionCanceled("已取消"))
        except ExecutionTimeout as exc:
            self._fail(record, control, exc)
        except Exception as exc:  # noqa: BLE001
            self._fail(record, control, exc)
        finally:
            control.close()
            self._persist(record, logs, control, emit=None)
            self._unregister(record.run_id, control)
        return self._run_result(record, logs)

    def _consume(self, record: ExecutionRecord, control: ExecutionControl,
                 logs: dict[str, dict[str, Any]], emit: Callable[[str, str], None] | None) -> None:
        payload = record._payload
        options = (loads(payload, {}) or {}).get("options") or {}
        timeout = int(options.get("timeoutMs") or 120_000)
        control.start(timeout + self.settings.execution_transport_grace_ms)
        with self.ai.open_execution(payload) as response:
            control.attach(response)
            for event, body in iter_events(response.iter_lines(), self.settings.execution_max_event_chars):
                control.check_stopped()
                self._handle_event(record, logs, event, body)
                if event in {"run_finished", "run_failed"}:
                    record._terminal = event, body
                    break
                if event != "done" and emit is not None:
                    emit(event, body)

    def _handle_event(self, record: ExecutionRecord, logs: dict[str, dict[str, Any]],
                      event: str, body: str) -> None:
        try:
            node = json.loads(body) if body and body.strip() else {}
        except ValueError as exc:
            raise BizError(f"执行事件处理失败: {event}") from exc
        if not isinstance(node, dict):
            raise BizError(f"执行事件处理失败: {event}")
        if event == "node_started":
            item = {
                "id": None,
                "run_id": record.run_id,
                "workflow_id": record.workflow_id,
                "node_id": str(node.get("nodeId") or ""),
                "node_type": str(node.get("nodeType") or ""),
                "node_name": str(node.get("nodeName") or ""),
                "seq": int(node.get("seq") or 0),
                "status": RUNNING,
                "cache_hit": False,
                "input_data": None,
                "output_data": None,
                "error_message": None,
                "elapsed_ms": 0,
                "started_at": datetime.now(),
                "finished_at": None,
            }
            logs[item["node_id"]] = item
            self._save_node(item)
        elif event == "node_finished":
            item = logs.get(str(node.get("nodeId") or ""))
            if item is not None:
                item["status"] = SUCCESS
                item["output_data"] = dumps(node.get("output"))
                item["elapsed_ms"] = int(node.get("elapsedMs") or 0)
                item["finished_at"] = datetime.now()
                item["cache_hit"] = bool(node.get("cacheHit"))
                self._save_node(item)
                metrics.inc("agentflow_nodes_total", type=item["node_type"] or "unknown", status=SUCCESS)
                if item["cache_hit"]:
                    metrics.inc("agentflow_execution_resume_node_hits_total")
                else:
                    self._apply_usage(record, node.get("output"))
        elif event == "node_failed":
            item = logs.get(str(node.get("nodeId") or ""))
            if item is not None:
                item["status"] = FAILED
                error = node.get("error") if isinstance(node.get("error"), dict) else {}
                item["error_message"] = str(error.get("message") or "执行失败")
                item["elapsed_ms"] = int(node.get("elapsedMs") or 0)
                item["finished_at"] = datetime.now()
                self._save_node(item)
                metrics.inc("agentflow_nodes_total", type=item["node_type"] or "unknown", status=FAILED)
        elif event == "run_finished":
            record.status = SUCCESS
            record.output_data = dumps(node.get("output"))
            record.elapsed_ms = int(node.get("elapsedMs") or 0)
            record.finished_at = datetime.now()
        elif event == "run_failed":
            record.status = FAILED
            error = node.get("error") if isinstance(node.get("error"), dict) else {}
            record.error_message = str(error.get("message") or "执行失败")
            record.elapsed_ms = int(node.get("elapsedMs") or 0)
            record.finished_at = datetime.now()

    def _save_node(self, item: dict[str, Any]) -> None:
        with session_scope() as session:
            if item.get("id") is None:
                row = ExecutionNodeLog(
                    run_id=item["run_id"],
                    workflow_id=item["workflow_id"],
                    node_id=item["node_id"],
                    node_type=item["node_type"],
                    node_name=item["node_name"],
                    seq=item["seq"],
                    status=item["status"],
                    cache_hit=item["cache_hit"],
                    input_data=item["input_data"],
                    output_data=item["output_data"],
                    error_message=item["error_message"],
                    elapsed_ms=item["elapsed_ms"],
                    started_at=item["started_at"],
                    finished_at=item["finished_at"],
                )
                session.add(row)
                session.flush()
                item["id"] = row.id
            else:
                row = session.get(ExecutionNodeLog, item["id"])
                if row is None:
                    return
                row.status = item["status"]
                row.cache_hit = item["cache_hit"]
                row.output_data = item["output_data"]
                row.error_message = item["error_message"]
                row.elapsed_ms = item["elapsed_ms"]
                row.finished_at = item["finished_at"]

    def _persist(self, record: ExecutionRecord, logs: dict[str, dict[str, Any]],
                 control: ExecutionControl, emit: Callable[[str, str], None] | None) -> bool:
        try:
            if control.is_timed_out:
                metrics.inc("agentflow_execution_timeouts_total")
                record.status = FAILED
                record.error_message = "执行超时（Python 平台服务连接与读取期限）"
            if record.status == RUNNING:
                record.status = CANCELED if control.is_canceled else FAILED
                record.error_message = "已取消" if control.is_canceled else "执行中断"
            if record.finished_at is None:
                record.finished_at = datetime.now()
            if record.status != SUCCESS:
                record.elapsed_ms = self._elapsed_since(record)
            ordered = sorted(logs.values(), key=lambda item: item.get("seq") or 0)
            with session_scope() as session:
                for item in ordered:
                    if item["status"] == RUNNING:
                        item["status"] = CANCELED if record.status == CANCELED else FAILED
                        item["error_message"] = record.error_message
                        item["finished_at"] = record.finished_at
                        item["elapsed_ms"] = max(
                            0, self._elapsed(item["started_at"], record.finished_at)
                        )
                    row = session.get(ExecutionNodeLog, item["id"]) if item.get("id") else None
                    if row is None:
                        continue
                    row.status = item["status"]
                    row.error_message = item["error_message"]
                    row.elapsed_ms = item["elapsed_ms"]
                    row.finished_at = item["finished_at"]
                row = session.get(ExecutionRecord, record.id)
                if row is None:
                    raise RuntimeError(f"执行记录终态未写入: {record.run_id}")
                row.status = record.status
                row.output_data = record.output_data
                row.error_message = record.error_message
                row.elapsed_ms = record.elapsed_ms
                row.finished_at = record.finished_at
                row.prompt_tokens = record.prompt_tokens
                row.completion_tokens = record.completion_tokens
                row.total_tokens = record.total_tokens
                row.cost_usd = record.cost_usd
            metrics.inc("agentflow_executions_total", status=record.status or "UNKNOWN")
            return True
        except Exception as exc:
            metrics.inc("agentflow_execution_persistence_failures_total")
            record.status = FAILED
            record.error_message = "执行结果持久化失败"
            log.error("failed to persist execution %s, runId=%s", record.id, record.run_id, exc_info=exc)
            try:
                with session_scope() as session:
                    row = session.get(ExecutionRecord, record.id)
                    if row is not None:
                        row.status = FAILED
                        row.error_message = record.error_message
                        row.finished_at = record.finished_at or datetime.now()
            except Exception:  # noqa: BLE001, S110
                pass
            return False

    def _fail(self, record: ExecutionRecord, control: ExecutionControl, error: Exception) -> None:
        if control.is_canceled:
            record.status = CANCELED
            record.error_message = "已取消"
        elif control.is_timed_out:
            record.status = FAILED
            record.error_message = "执行超时（Python 平台服务连接与读取期限）"
        elif record.status == RUNNING:
            record.status = FAILED
            record.error_message = str(error) or "执行上游连接失败"
            log.error("execution failed, runId=%s: %s", record.run_id, error)
        record.finished_at = datetime.now()

    def _apply_usage(self, record: ExecutionRecord, output: Any) -> None:
        if not isinstance(output, dict):
            return
        usage = output.get("usage")
        if not isinstance(usage, dict):
            return
        prompt = self._first_int(usage, "promptTokens", "prompt_tokens", "input_tokens", "inputTokens")
        completion = self._first_int(
            usage, "completionTokens", "completion_tokens", "output_tokens", "outputTokens"
        )
        total = self._first_int(usage, "totalTokens", "total_tokens")
        if total <= 0:
            total = prompt + completion
        if prompt == 0 and completion == 0 and total == 0:
            return
        record.prompt_tokens = int(record.prompt_tokens or 0) + prompt
        record.completion_tokens = int(record.completion_tokens or 0) + completion
        record.total_tokens = int(record.total_tokens or 0) + total
        model = str(output.get("model") or "unknown")
        metrics.inc("agentflow_llm_tokens_total", prompt, model=model, kind="prompt")
        metrics.inc("agentflow_llm_tokens_total", completion, model=model, kind="completion")
        cost = self.pricing.estimate(model, prompt, completion)
        record.cost_usd = (Decimal(str(record.cost_usd or 0)) + cost).quantize(Decimal("0.000001"))

    @staticmethod
    def _first_int(node: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = node.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return 0

    def _run_result(self, record: ExecutionRecord, logs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        nodes = []
        for item in sorted(logs.values(), key=lambda value: value.get("seq") or 0):
            nodes.append(
                {
                    "nodeId": item["node_id"],
                    "nodeType": item["node_type"],
                    "nodeName": item["node_name"],
                    "status": item["status"],
                    "cacheHit": item["cache_hit"],
                    "output": loads(item["output_data"]) if item["output_data"] else None,
                    "elapsedMs": item["elapsed_ms"],
                    "errorMessage": item["error_message"],
                }
            )
        return {
            "runId": record.run_id,
            "status": record.status,
            "outputs": loads(record.output_data) if record.output_data else None,
            "nodeStatus": nodes,
            "promptTokens": record.prompt_tokens,
            "completionTokens": record.completion_tokens,
            "totalTokens": record.total_tokens,
            "costUsd": float(record.cost_usd or 0),
            "elapsedMs": record.elapsed_ms,
            "errorMessage": record.error_message,
        }

    # ------------------------------------------------------------------ helpers
    def _reject(self, record: ExecutionRecord, control: ExecutionControl) -> None:
        self._unregister(record.run_id, control)
        metrics.inc("agentflow_execution_rejected_total")
        with session_scope() as session:
            row = session.get(ExecutionRecord, record.id)
            if row is not None:
                row.status = FAILED
                row.error_message = "执行线程池已满或已关闭，请稍后重试"
                row.elapsed_ms = self._elapsed_since(row)
                row.finished_at = datetime.now()
        raise BizError("执行线程池已满或已关闭，请稍后重试", 5030, 503)

    def _require(self, session: Session, run_id: str, user: CurrentUser) -> ExecutionRecord:
        record = session.scalar(
            select(ExecutionRecord).where(
                ExecutionRecord.run_id == run_id, ExecutionRecord.deleted == 0
            )
        )
        if record is None or (not user.is_admin and record.user_id != user.id):
            raise not_found(f"执行记录不存在: {run_id}")
        return record

    def _register(self, run_id: str, control: ExecutionControl) -> None:
        with self._lock:
            self._running[run_id] = control
            metrics.gauge("agentflow_executions_running", len(self._running))

    def _unregister(self, run_id: str, control: ExecutionControl) -> None:
        with self._lock:
            if self._running.get(run_id) is control:
                self._running.pop(run_id, None)
            metrics.gauge("agentflow_executions_running", len(self._running))

    def _find_control(self, run_id: str) -> ExecutionControl | None:
        with self._lock:
            return self._running.get(run_id)

    @staticmethod
    def _summary(record: ExecutionRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "runId": record.run_id,
            "workflowId": record.workflow_id,
            "workflowName": record.workflow_name,
            "status": record.status,
            "nodeCount": record.node_count,
            "flowVersion": record.flow_version,
            "promptTokens": record.prompt_tokens,
            "completionTokens": record.completion_tokens,
            "totalTokens": record.total_tokens,
            "costUsd": float(record.cost_usd or 0),
            "elapsedMs": record.elapsed_ms,
            "errorMessage": record.error_message,
            "startedAt": iso(record.started_at),
            "finishedAt": iso(record.finished_at),
        }

    @staticmethod
    def _node_vo(item: ExecutionNodeLog) -> dict[str, Any]:
        return {
            "nodeId": item.node_id,
            "nodeType": item.node_type,
            "nodeName": item.node_name,
            "seq": item.seq,
            "status": item.status,
            "cacheHit": bool(item.cache_hit),
            "output": item.output_data,
            "errorMessage": item.error_message,
            "elapsedMs": item.elapsed_ms,
            "startedAt": iso(item.started_at),
            "finishedAt": iso(item.finished_at),
        }

    def _elapsed_since(self, record: ExecutionRecord) -> int:
        return self._elapsed(record.started_at, datetime.now())

    @staticmethod
    def _elapsed(started_at: datetime | None, now: datetime) -> int:
        if started_at is None:
            return 0
        return max(0, int((now - started_at).total_seconds() * 1000))

    def _providers(self):
        from app.services.providers import ProviderService

        return ProviderService()

    def _mcp(self):
        from app.services.mcp import McpService

        return McpService()


_execution: ExecutionService | None = None


def get_execution_service() -> ExecutionService:
    global _execution
    if _execution is None:
        _execution = ExecutionService()
    return _execution
