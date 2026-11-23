from __future__ import annotations

import time
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _event(event_type: str, **fields: Any) -> dict:
    payload = {
        "eventType": event_type,
        "nodeId": fields.get("nodeId"),
        "nodeName": fields.get("nodeName"),
        "status": fields.get("status"),
        "message": fields.get("message"),
        "data": fields.get("data"),
        "timestamp": _now_ms(),
    }
    return payload


def workflow_start(execution_id: Any) -> dict:
    return _event(
        "WORKFLOW_START",
        message="工作流开始执行",
        data=execution_id,
    )


def node_start(node_id: str, node_name: str) -> dict:
    return _event(
        "NODE_START",
        nodeId=node_id,
        nodeName=node_name,
        status="RUNNING",
        message="节点开始执行",
    )


def node_success(node_id: str, node_name: str, output: Any, duration: int) -> dict:
    return _event(
        "NODE_SUCCESS",
        nodeId=node_id,
        nodeName=node_name,
        status="SUCCESS",
        message=f"节点执行成功,耗时 {duration}ms",
        data=output,
    )


def node_error(node_id: str, node_name: str, error: str) -> dict:
    return _event(
        "NODE_ERROR",
        nodeId=node_id,
        nodeName=node_name,
        status="FAILED",
        message=error,
    )


def workflow_complete(status: str, output: Any, duration: int) -> dict:
    return _event(
        "WORKFLOW_COMPLETE",
        status=status,
        message=f"工作流执行完成,总耗时 {duration}ms",
        data=output,
    )


def node_progress(node_id: str, node_name: str, message: str, data: Any) -> dict:
    return _event(
        "NODE_PROGRESS",
        nodeId=node_id,
        nodeName=node_name,
        status="RUNNING",
        message=message,
        data=data,
    )
