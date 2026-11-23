from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import events, executors
from .db import first_text, jdump, jload, now, text_or_none
from .models import ExecutionRecord, ExecutionSnapshot, ExecutionVariable

logger = logging.getLogger("agentflow.engine")

EventCallback = Optional[Callable[[dict], None]]


class WorkflowConfigError(ValueError):
    pass


def parse_workflow(flow_data: Optional[str]) -> dict:
    try:
        root = json.loads(flow_data or "{}")
    except json.JSONDecodeError as exc:
        raise WorkflowConfigError(f"工作流配置不是合法 JSON: {exc}") from exc
    if not isinstance(root, dict):
        raise WorkflowConfigError("工作流配置必须是 JSON 对象")

    nodes: list[dict] = []
    for item in root.get("nodes") or []:
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        node_type = item.get("type")
        if (not node_type or node_type == "workflow") and data.get("type"):
            node_type = data.get("type")
        position = item.get("position") if isinstance(item.get("position"), dict) else None
        nodes.append(
            {
                "id": item.get("id"),
                "type": node_type,
                "data": data,
                "position": position,
            }
        )

    edges: list[dict] = []
    for item in root.get("edges") or []:
        if not isinstance(item, dict):
            continue
        edges.append(
            {
                "id": item.get("id"),
                "source": item.get("source"),
                "target": item.get("target"),
                "sourceHandle": item.get("sourceHandle"),
                "targetHandle": item.get("targetHandle"),
            }
        )
    return {"nodes": nodes, "edges": edges}


def topological_sort(nodes: list[dict], edges: list[dict]) -> list[dict]:
    node_map = {node["id"]: node for node in nodes}
    dependencies: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    dependents: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source not in dependencies or target not in dependencies:
            continue
        dependencies[target].append(source)
        dependents[source].append(target)

    _detect_cycle(dependencies, nodes)

    in_degree = {node_id: len(deps) for node_id, deps in dependencies.items()}
    queue = [node_id for node_id in node_map if in_degree[node_id] == 0]
    result: list[dict] = []
    index = 0
    while index < len(queue):
        node_id = queue[index]
        index += 1
        result.append(node_map[node_id])
        for dependent in dependents[node_id]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    if len(result) != len(node_map):
        raise WorkflowConfigError("工作流存在循环依赖,无法完成拓扑排序")
    return result


def _detect_cycle(dependencies: dict[str, list[str]], nodes: list[dict]) -> None:
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(node_id: str) -> bool:
        if node_id in stack:
            return True
        if node_id in visited:
            return False
        visited.add(node_id)
        stack.add(node_id)
        for dependency in dependencies.get(node_id, []):
            if visit(dependency):
                return True
        stack.discard(node_id)
        return False

    for node in nodes:
        if visit(node["id"]):
            raise WorkflowConfigError(f"工作流存在循环依赖,节点: {node['id']}")


def strip_runtime_value(value: Any, seen: Optional[set[int]] = None) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return "[Circular]"
    if isinstance(value, dict):
        seen.add(identity)
        stripped: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text == "__nodeOutputs__":
                continue
            stripped[key_text] = strip_runtime_value(item, seen)
        seen.discard(identity)
        return stripped
    if isinstance(value, list):
        seen.add(identity)
        stripped_list = [strip_runtime_value(item, seen) for item in value]
        seen.discard(identity)
        return stripped_list
    return value


def strip_runtime_fields(value: Optional[dict]) -> dict:
    result = strip_runtime_value(value or {}, set())
    return result if isinstance(result, dict) else {}


def _build_edge_indexes(edges: list[dict]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    edges_by_source: dict[str, list[dict]] = {}
    edges_by_target: dict[str, list[dict]] = {}
    for edge in edges:
        edges_by_source.setdefault(edge.get("source"), []).append(edge)
        edges_by_target.setdefault(edge.get("target"), []).append(edge)
    return edges_by_source, edges_by_target


def _node_name(node: dict) -> str:
    label = (node.get("data") or {}).get("label")
    if isinstance(label, str) and label.strip():
        return label
    return str(node.get("type"))


def _resolve_node_input(
    node: dict,
    node_outputs: dict[str, dict],
    edges_by_target: dict[str, list[dict]],
    fallback_input: dict,
) -> dict:
    incoming = edges_by_target.get(node.get("id"))
    if not incoming:
        return fallback_input
    resolved: dict[str, Any] = {}
    for edge in incoming:
        source_output = node_outputs.get(edge.get("source"))
        if source_output is not None:
            resolved.update(source_output)
    if not resolved:
        return fallback_input
    resolved["__nodeOutputs__"] = node_outputs
    return resolved


def _mark_skipped_nodes(
    condition_node_id: str,
    selected_branch: Optional[str],
    edges_by_source: dict[str, list[dict]],
    edges_by_target: dict[str, list[dict]],
    skipped_nodes: set[str],
) -> None:
    out_edges = edges_by_source.get(condition_node_id)
    if not out_edges:
        return
    if not any(edge.get("sourceHandle") is not None for edge in out_edges):
        return

    active_targets: set[str] = set()
    inactive_targets: set[str] = set()
    for edge in out_edges:
        handle = edge.get("sourceHandle")
        if handle is not None and handle == selected_branch:
            active_targets.add(edge.get("target"))
        elif handle is None and selected_branch == "default":
            active_targets.add(edge.get("target"))
        else:
            inactive_targets.add(edge.get("target"))

    for target in inactive_targets:
        if target not in active_targets:
            _mark_downstream_skipped(target, skipped_nodes, edges_by_source, edges_by_target)


def _mark_downstream_skipped(
    node_id: str,
    skipped_nodes: set[str],
    edges_by_source: dict[str, list[dict]],
    edges_by_target: dict[str, list[dict]],
) -> None:
    if node_id in skipped_nodes:
        return
    incoming = edges_by_target.get(node_id)
    if incoming and len(incoming) > 1:
        for edge in incoming:
            if edge.get("source") not in skipped_nodes:
                return
    skipped_nodes.add(node_id)
    for edge in edges_by_source.get(node_id) or []:
        _mark_downstream_skipped(edge.get("target"), skipped_nodes, edges_by_source, edges_by_target)


def _create_running_record(db: Session, flow_id: int, input_data: str) -> ExecutionRecord:
    record = ExecutionRecord()
    record.flow_id = flow_id
    record.input_data = jdump({"input": input_data})
    record.status = "RUNNING"
    record.node_results = "[]"
    record.duration = 0
    record.executed_at = now()
    record.deleted = 0
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _snapshot_start(
    db: Session,
    execution_id: int,
    flow_id: int,
    node: dict,
    node_input: dict,
    execution_order: int,
) -> Optional[ExecutionSnapshot]:
    if execution_id is None:
        return None
    snapshot = db.execute(
        select(ExecutionSnapshot)
        .where(
            ExecutionSnapshot.execution_id == execution_id,
            ExecutionSnapshot.node_id == str(node.get("id")),
        )
        .limit(1)
    ).scalar_one_or_none()
    if snapshot is None:
        snapshot = ExecutionSnapshot()
        snapshot.execution_id = execution_id
        snapshot.flow_id = flow_id
        snapshot.node_id = str(node.get("id"))
        snapshot.node_type = str(node.get("type"))
        snapshot.node_name = _node_name(node)
        snapshot.retry_count = 0
        snapshot.execution_order = execution_order
        db.add(snapshot)
    else:
        snapshot.retry_count = (snapshot.retry_count or 0) + 1

    snapshot.node_type = str(node.get("type"))
    snapshot.node_name = _node_name(node)
    snapshot.execution_order = execution_order
    snapshot.status = "RUNNING"
    snapshot.input_data = jdump(strip_runtime_fields(node_input))
    snapshot.output_data = None
    snapshot.error_message = None
    snapshot.started_at = now()
    snapshot.completed_at = None
    snapshot.duration = None
    snapshot.created_at = snapshot.created_at or now()
    snapshot.updated_at = now()
    db.commit()
    db.refresh(snapshot)
    return snapshot


def _snapshot_success(db: Session, snapshot: Optional[ExecutionSnapshot], output: dict, duration: int) -> None:
    if snapshot is None or snapshot.id is None:
        return
    snapshot.status = "SUCCESS"
    snapshot.output_data = jdump(strip_runtime_fields(output))
    snapshot.error_message = None
    snapshot.completed_at = now()
    snapshot.duration = duration
    snapshot.updated_at = now()
    db.commit()


def _snapshot_failed(db: Session, snapshot: Optional[ExecutionSnapshot], error: str, duration: int) -> None:
    if snapshot is None or snapshot.id is None:
        return
    snapshot.status = "FAILED"
    snapshot.error_message = error
    snapshot.completed_at = now()
    snapshot.duration = duration
    snapshot.updated_at = now()
    db.commit()


class DagEngine:
    engine_type = "dag"

    def execute(
        self,
        db: Session,
        workflow,
        input_data: str,
        on_event: EventCallback = None,
    ) -> dict:
        start_time = time.time()
        config = parse_workflow(workflow.flow_data)
        sorted_nodes = topological_sort(config["nodes"], config["edges"])
        edges = config["edges"]
        edges_by_source, edges_by_target = _build_edge_indexes(edges)
        record = _create_running_record(db, workflow.id, input_data)

        if on_event:
            on_event(events.workflow_start(record.id))

        return self._execute_nodes(
            db=db,
            record=record,
            flow_id=workflow.id,
            input_data=input_data,
            sorted_nodes=sorted_nodes,
            edges_by_source=edges_by_source,
            edges_by_target=edges_by_target,
            resume_state=_resume_state(),
            start_time=start_time,
            on_event=on_event,
        )

    def resume(
        self,
        db: Session,
        workflow,
        execution_id: int,
        request: Optional[dict],
        on_event: EventCallback = None,
    ) -> dict:
        record = db.execute(
            select(ExecutionRecord).where(
                ExecutionRecord.id == execution_id, ExecutionRecord.deleted == 0
            )
        ).scalar_one_or_none()
        if record is None or record.flow_id != workflow.id:
            raise ValueError("执行记录不存在或不属于当前工作流")

        request = request or {}
        config = parse_workflow(workflow.flow_data)
        sorted_nodes = topological_sort(config["nodes"], config["edges"])
        edges = config["edges"]
        edges_by_source, edges_by_target = _build_edge_indexes(edges)

        snapshots = list(
            db.execute(
                select(ExecutionSnapshot)
                .where(ExecutionSnapshot.execution_id == execution_id)
                .order_by(ExecutionSnapshot.execution_order.asc())
            ).scalars()
        )
        snapshots_by_node: dict[str, ExecutionSnapshot] = {}
        for snapshot in snapshots:
            snapshots_by_node[str(snapshot.node_id)] = snapshot

        start_node_id = self._resolve_resume_start_node_id(sorted_nodes, snapshots_by_node, request)
        if start_node_id is None:
            return self._response_from_record(record, snapshots)

        input_data = self._extract_input_value(record.input_data)
        state = self._build_resume_state(
            sorted_nodes,
            snapshots_by_node,
            edges_by_source,
            edges_by_target,
            start_node_id,
            bool(request.get("skipSuccessNodes", True)),
        )
        modified_variables = request.get("modifiedVariables")
        state["modifiedVariables"] = dict(modified_variables) if isinstance(modified_variables, dict) else {}
        self._save_modified_variables(db, execution_id, state["modifiedVariables"])

        record.status = "RUNNING"
        record.error_message = None
        db.commit()

        start_time = time.time()
        if on_event:
            on_event(events.workflow_start(record.id))

        return self._execute_nodes(
            db=db,
            record=record,
            flow_id=workflow.id,
            input_data=input_data,
            sorted_nodes=sorted_nodes,
            edges_by_source=edges_by_source,
            edges_by_target=edges_by_target,
            resume_state=state,
            start_time=start_time,
            on_event=on_event,
        )

    def _execute_nodes(
        self,
        db: Session,
        record: ExecutionRecord,
        flow_id: int,
        input_data: str,
        sorted_nodes: list[dict],
        edges_by_source: dict[str, list[dict]],
        edges_by_target: dict[str, list[dict]],
        resume_state: dict,
        start_time: float,
        on_event: EventCallback,
    ) -> dict:
        node_results: list[dict] = list(resume_state["restoredNodeResults"])
        node_outputs: dict[str, dict] = dict(resume_state["nodeOutputs"])
        skipped_nodes: set[str] = set(resume_state["skippedNodes"])

        current_input: dict[str, Any] = {"input": input_data}
        current_input.update(resume_state["latestOutput"])
        current_input.update(resume_state["modifiedVariables"])

        status = "SUCCESS"
        error_message: Optional[str] = None
        output_data: Optional[str] = None
        start_reached = resume_state["startNodeId"] is None

        node_index = {node["id"]: index for index, node in enumerate(sorted_nodes)}

        try:
            for node in sorted_nodes:
                if not start_reached:
                    if node["id"] == resume_state["startNodeId"]:
                        start_reached = True
                    else:
                        continue

                if node["id"] in skipped_nodes:
                    continue

                node_input = _resolve_node_input(node, node_outputs, edges_by_target, current_input)
                if resume_state["modifiedVariables"]:
                    node_input = dict(node_input)
                    node_input.update(resume_state["modifiedVariables"])

                node_start = time.time()
                snapshot = _snapshot_start(
                    db, record.id, flow_id, node, node_input, node_index.get(node["id"], 0)
                )
                if on_event:
                    on_event(events.node_start(node["id"], str(node.get("type"))))

                node_result: dict[str, Any] = {
                    "nodeId": node.get("id"),
                    "nodeName": node.get("type"),
                    "status": None,
                    "input": jdump(strip_runtime_fields(node_input)),
                    "output": None,
                    "duration": None,
                    "error": None,
                }

                try:
                    executor = executors.get_executor(str(node.get("type")))
                    progress = None
                    if on_event:
                        def progress(message: str, data: Any) -> None:
                            on_event(
                                events.node_progress(node["id"], str(node.get("type")), message, data)
                            )

                    raw_output = executor.execute(db, node, node_input, progress)
                    output = strip_runtime_fields(raw_output)
                    node_outputs[str(node["id"])] = output

                    node_result["status"] = "SUCCESS"
                    node_result["output"] = jdump(output)
                    node_duration = int((time.time() - node_start) * 1000)
                    node_result["duration"] = node_duration
                    _snapshot_success(db, snapshot, output, node_duration)

                    if on_event:
                        on_event(
                            events.node_success(
                                node["id"],
                                str(node.get("type")),
                                {
                                    "input": strip_runtime_fields(node_input),
                                    "output": output,
                                    "duration": node_duration,
                                },
                                node_duration,
                            )
                        )

                    current_input = output
                    if node.get("type") == "condition":
                        selected_branch = raw_output.get("__selectedBranch__")
                        _mark_skipped_nodes(
                            str(node["id"]),
                            selected_branch,
                            edges_by_source,
                            edges_by_target,
                            skipped_nodes,
                        )
                except Exception as exc:
                    logger.exception("节点执行失败: %s", node.get("id"))
                    node_result["status"] = "FAILED"
                    node_result["error"] = str(exc)
                    status = "FAILED"
                    error_message = f"节点 {node.get('id')} 执行失败: {exc}"
                    _snapshot_failed(db, snapshot, str(exc), int((time.time() - node_start) * 1000))
                    if on_event:
                        on_event(events.node_error(node["id"], str(node.get("type")), str(exc)))
                    raise
                finally:
                    node_result["duration"] = int((time.time() - node_start) * 1000)
                    node_results.append(node_result)

            output_data = jdump(strip_runtime_fields(current_input))
        except Exception as exc:
            status = "FAILED"
            if error_message is None:
                error_message = str(exc)

        duration = int((time.time() - start_time) * 1000)
        if on_event:
            on_event(events.workflow_complete(status, current_input, duration))

        input_data_json = jdump({"input": input_data})
        record.flow_id = flow_id
        record.input_data = input_data_json
        record.output_data = output_data
        record.status = status
        record.node_results = jdump(node_results)
        record.error_message = error_message
        record.duration = duration
        db.commit()

        return {
            "executionId": record.id,
            "status": status,
            "inputData": input_data_json,
            "nodeResults": node_results,
            "outputData": output_data,
            "duration": duration,
            "errorMessage": error_message,
        }

    @staticmethod
    def _resolve_resume_start_node_id(
        sorted_nodes: list[dict],
        snapshots_by_node: dict[str, ExecutionSnapshot],
        request: dict,
    ) -> Optional[str]:
        explicit = request.get("startNodeId")
        if isinstance(explicit, str) and explicit.strip():
            return explicit

        for node in sorted_nodes:
            snapshot = snapshots_by_node.get(str(node["id"]))
            if snapshot is not None and snapshot.status == "FAILED":
                return str(node["id"])

        for node in sorted_nodes:
            snapshot = snapshots_by_node.get(str(node["id"]))
            if snapshot is None or snapshot.status not in ("SUCCESS", "SKIPPED"):
                return str(node["id"])
        return None

    def _build_resume_state(
        self,
        sorted_nodes: list[dict],
        snapshots_by_node: dict[str, ExecutionSnapshot],
        edges_by_source: dict[str, list[dict]],
        edges_by_target: dict[str, list[dict]],
        start_node_id: str,
        skip_success_nodes: bool,
    ) -> dict:
        state = {
            "startNodeId": start_node_id,
            "restoredNodeResults": [],
            "nodeOutputs": {},
            "skippedNodes": set(),
            "latestOutput": {},
            "modifiedVariables": {},
        }
        if not skip_success_nodes:
            return state

        for node in sorted_nodes:
            if str(node["id"]) == start_node_id:
                break
            snapshot = snapshots_by_node.get(str(node["id"]))
            if snapshot is None or snapshot.status != "SUCCESS":
                continue
            output = jload(snapshot.output_data, {}) or {}
            if not isinstance(output, dict):
                output = {}
            state["nodeOutputs"][str(node["id"])] = output
            state["latestOutput"] = output
            state["restoredNodeResults"].append(self._node_result_from_snapshot(snapshot))
            if node.get("type") == "condition":
                selected = output.get("__selectedBranch__")
                selected_branch = selected if isinstance(selected, str) else "default"
                _mark_skipped_nodes(
                    str(node["id"]),
                    selected_branch,
                    edges_by_source,
                    edges_by_target,
                    state["skippedNodes"],
                )
        return state

    @staticmethod
    def _node_result_from_snapshot(snapshot: ExecutionSnapshot) -> dict:
        return {
            "nodeId": snapshot.node_id,
            "nodeName": snapshot.node_type,
            "status": snapshot.status,
            "input": snapshot.input_data,
            "output": snapshot.output_data,
            "duration": snapshot.duration if snapshot.duration is not None else 0,
            "error": snapshot.error_message,
        }

    def _response_from_record(self, record: ExecutionRecord, snapshots: list[ExecutionSnapshot]) -> dict:
        node_results: list[dict]
        parsed = jload(record.node_results, None)
        if record.node_results and record.node_results.strip() and isinstance(parsed, list):
            node_results = parsed
        else:
            node_results = [self._node_result_from_snapshot(snapshot) for snapshot in snapshots]
        return {
            "executionId": record.id,
            "status": record.status,
            "inputData": record.input_data,
            "nodeResults": node_results,
            "outputData": record.output_data,
            "duration": record.duration,
            "errorMessage": record.error_message,
        }

    @staticmethod
    def _extract_input_value(input_data_json: Optional[str]) -> str:
        parsed = jload(input_data_json, {}) if input_data_json else {}
        if isinstance(parsed, dict):
            value = parsed.get("input")
            return "" if value is None else str(value)
        return ""

    def _save_modified_variables(self, db: Session, execution_id: int, modified_variables: dict) -> None:
        if not modified_variables:
            return
        for name, value in modified_variables.items():
            variable = db.execute(
                select(ExecutionVariable)
                .where(
                    ExecutionVariable.execution_id == execution_id,
                    ExecutionVariable.variable_name == str(name),
                )
                .limit(1)
            ).scalar_one_or_none()
            if variable is None:
                variable = ExecutionVariable()
                variable.execution_id = execution_id
                variable.variable_name = str(name)
                variable.variable_type = self._resolve_variable_type(value)
                variable.variable_value = jdump(value)
                variable.is_modified = 1
                db.add(variable)
            else:
                variable.variable_type = self._resolve_variable_type(value)
                variable.variable_value = jdump(value)
                variable.is_modified = 1
        db.commit()

    @staticmethod
    def _resolve_variable_type(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "BOOLEAN"
        if isinstance(value, (int, float)):
            return "NUMBER"
        if isinstance(value, (dict, list)):
            return "JSON"
        return "STRING"


def _resume_state() -> dict:
    return {
        "startNodeId": None,
        "restoredNodeResults": [],
        "nodeOutputs": {},
        "skippedNodes": set(),
        "latestOutput": {},
        "modifiedVariables": {},
    }


class LangGraphEngine:
    engine_type = "langgraph"

    def execute(self, db: Session, workflow, input_data: str, on_event: EventCallback = None) -> dict:
        start_time = time.time()
        status = "SUCCESS"
        error_message: Optional[str] = None
        if on_event:
            on_event(events.workflow_start(None))

        try:
            config = parse_workflow(workflow.flow_data)
            nodes = config["nodes"]
            edges = config["edges"]
            ordered_nodes = self._reachable_nodes(nodes, edges)
            state = {
                "inputData": input_data,
                "currentInput": {"input": input_data},
                "nodeOutputs": {},
                "status": "RUNNING",
            }

            for node in ordered_nodes:
                node_start = time.time()
                if on_event:
                    on_event(events.node_start(node["id"], str(node.get("type"))))
                current_input = state["currentInput"]
                if node.get("type") == "output":
                    current_input = dict(current_input)
                    current_input["__nodeOutputs__"] = state["nodeOutputs"]
                try:
                    executor = executors.get_executor(str(node.get("type")))
                    progress = None
                    if on_event:
                        def progress(message: str, data: Any) -> None:
                            on_event(events.node_progress(node["id"], str(node.get("type")), message, data))

                    output = executor.execute(db, node, current_input, progress)
                    duration = int((time.time() - node_start) * 1000)
                    state["nodeOutputs"][str(node["id"])] = output
                    state["currentInput"] = output
                    if on_event:
                        on_event(
                            events.node_success(
                                node["id"],
                                str(node.get("type")),
                                {"input": current_input, "output": output, "duration": duration},
                                duration,
                            )
                        )
                except Exception as exc:
                    logger.exception("LangGraph 节点执行失败: %s", node.get("id"))
                    state["status"] = "FAILED"
                    state["errorMessage"] = f"节点 {node.get('id')} 执行失败: {exc}"
                    if on_event:
                        on_event(events.node_error(node["id"], str(node.get("type")), str(exc)))

            if state["status"] not in ("SUCCESS", "RUNNING"):
                status = "FAILED"
                error_message = state.get("errorMessage")

            final_output = state["currentInput"]
            output_data_json = jdump(final_output)
            node_results = self._extract_node_results(state, nodes)
            duration = int((time.time() - start_time) * 1000)

            record = ExecutionRecord()
            record.flow_id = workflow.id
            record.input_data = jdump({"input": input_data})
            record.output_data = output_data_json
            record.status = status
            record.node_results = jdump(node_results)
            record.error_message = error_message
            record.duration = duration
            record.executed_at = now()
            record.deleted = 0
            db.add(record)
            db.commit()
            db.refresh(record)

            if on_event:
                on_event(events.workflow_complete(status, final_output, duration))

            return {
                "executionId": record.id,
                "status": status,
                "inputData": record.input_data,
                "nodeResults": node_results,
                "outputData": output_data_json,
                "duration": duration,
                "errorMessage": None,
            }
        except Exception as exc:
            logger.exception("LangGraph 工作流执行失败")
            duration = int((time.time() - start_time) * 1000)
            record = ExecutionRecord()
            record.flow_id = workflow.id
            record.input_data = jdump({"input": input_data})
            record.status = "FAILED"
            record.error_message = str(exc)
            record.duration = duration
            record.executed_at = now()
            record.deleted = 0
            db.add(record)
            db.commit()
            db.refresh(record)
            if on_event:
                on_event(events.workflow_complete("FAILED", str(exc), duration))
            return {
                "executionId": record.id,
                "status": "FAILED",
                "inputData": record.input_data,
                "nodeResults": [],
                "outputData": None,
                "duration": duration,
                "errorMessage": str(exc),
            }

    @staticmethod
    def _reachable_nodes(nodes: list[dict], edges: list[dict]) -> list[dict]:
        sorted_nodes = topological_sort(nodes, edges)
        if not nodes:
            return []
        targets = {edge.get("target") for edge in edges}
        entry = next((node for node in nodes if node["id"] not in targets), nodes[0])
        adjacency: dict[str, list[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.get("source"), []).append(edge.get("target"))
        reachable: set[str] = set()
        stack = [entry["id"]]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(adjacency.get(node_id, []))
        return [node for node in sorted_nodes if node["id"] in reachable]

    @staticmethod
    def _extract_node_results(state: dict, nodes: list[dict]) -> list[dict]:
        node_id_to_name = {str(node["id"]): node.get("type") for node in nodes}
        results: list[dict] = []
        for node_id, output in state["nodeOutputs"].items():
            results.append(
                {
                    "nodeId": node_id,
                    "nodeName": node_id_to_name.get(node_id, node_id),
                    "status": "SUCCESS",
                    "output": jdump(output),
                }
            )
        return results


dag_engine = DagEngine()
langgraph_engine = LangGraphEngine()


def select_engine(workflow):
    engine_type = (workflow.engine_type or "").strip().lower() or "dag"
    if engine_type == "langgraph":
        return langgraph_engine
    return dag_engine
