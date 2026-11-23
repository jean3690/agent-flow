from __future__ import annotations

from typing import Any, Optional

from .db import format_dt, jload
from .models import (
    ExecutionRecord,
    ExecutionSnapshot,
    ExecutionVariable,
    NodeDefinition,
    Workflow,
)


def workflow_to_dict(workflow: Workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "flowData": workflow.flow_data,
        "engineType": workflow.engine_type,
        "createdAt": format_dt(workflow.created_at),
        "updatedAt": format_dt(workflow.updated_at),
    }


def node_definition_to_dict(node: NodeDefinition) -> dict:
    return {
        "id": node.id,
        "nodeType": node.node_type,
        "displayName": node.display_name,
        "category": node.category,
        "icon": node.icon,
        "inputSchema": node.input_schema,
        "outputSchema": node.output_schema,
        "configSchema": node.config_schema,
        "createdAt": format_dt(node.created_at),
        "updatedAt": format_dt(node.updated_at),
        "deleted": node.deleted,
    }


def execution_response(record: ExecutionRecord) -> dict:
    node_results = jload(record.node_results, [])
    if not isinstance(node_results, list):
        node_results = []
    return {
        "executionId": record.id,
        "status": record.status,
        "inputData": record.input_data,
        "nodeResults": node_results,
        "outputData": record.output_data,
        "duration": record.duration,
        "errorMessage": record.error_message,
    }


def snapshot_to_dict(snapshot: ExecutionSnapshot) -> dict:
    input_data = jload(snapshot.input_data, {})
    output_data = jload(snapshot.output_data, {})
    return {
        "id": snapshot.id,
        "executionId": snapshot.execution_id,
        "flowId": snapshot.flow_id,
        "nodeId": snapshot.node_id,
        "nodeType": snapshot.node_type,
        "nodeName": snapshot.node_name,
        "status": snapshot.status,
        "inputData": input_data if isinstance(input_data, dict) else {},
        "outputData": output_data if isinstance(output_data, dict) else {},
        "errorMessage": snapshot.error_message,
        "startedAt": format_dt(snapshot.started_at),
        "completedAt": format_dt(snapshot.completed_at),
        "duration": snapshot.duration,
        "retryCount": snapshot.retry_count,
        "executionOrder": snapshot.execution_order,
        "createdAt": format_dt(snapshot.created_at),
    }


def variable_to_dict(variable: ExecutionVariable) -> dict:
    return {
        "id": variable.id,
        "executionId": variable.execution_id,
        "variableName": variable.variable_name,
        "variableType": variable.variable_type,
        "variableValue": variable.variable_value,
        "isModified": bool(variable.is_modified and variable.is_modified == 1),
        "createdAt": format_dt(variable.created_at),
        "updatedAt": format_dt(variable.updated_at),
    }
