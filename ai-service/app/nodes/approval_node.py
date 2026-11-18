from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from app.core.errors import NodeExecutionError
from app.core.template import render
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import names_for, source_value
from app.schemas.flow import FlowNode

MAX_WAIT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2


def _content_text(node: FlowNode, state: FlowState, ctx: NodeContext) -> str:
    value = source_value(node, state, ctx, "content")
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False)


@register
class HumanApprovalNodeExecutor(NodeExecutor):
    """人工审批：创建审批任务并轮询结果，超时或驳回按配置收尾。"""

    type = "human_approval"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        config = node.config or {}
        names = names_for(state)
        title = render(str(config.get("title") or "工作流审批"), names).strip() or "工作流审批"
        content = _content_text(node, state, ctx)
        wait_seconds = max(30, min(int(config.get("waitSeconds") or 120), MAX_WAIT_SECONDS))
        reject_behavior = str(config.get("rejectBehavior") or "fail").lower()
        auto_approve = bool(config.get("autoApprove", False)) or (ctx.settings.mock_mode or "").lower() == "always"

        if auto_approve:
            comment = "[auto] 演示模式自动通过" if not config.get("autoApprove") else "[auto] 节点配置自动通过"
            ctx.emit("node_log", nodeId=node.id, level="info", message="审批节点自动通过，不创建待办")
            return {
                "approved": True,
                "approvalId": None,
                "status": "APPROVED",
                "comment": comment,
                "decidedBy": None,
                "text": comment,
                "auto": True,
            }

        base_url = ctx.settings.java_service_base_url.rstrip("/")
        headers = {"X-Internal-Token": ctx.settings.internal_token}
        workflow_id = int(ctx.workflow_id) if str(ctx.workflow_id or "").isdigit() else None
        payload = {
            "runId": ctx.run_id,
            "workflowId": workflow_id,
            "nodeId": node.id,
            "userId": ctx.user_id,
            "title": title[:255],
            "content": content[:20000],
            "expiresInSeconds": wait_seconds,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(f"{base_url}/internal/approvals", json=payload, headers=headers)
                response.raise_for_status()
                task = (response.json() or {}).get("data") or {}
                approval_id = task.get("id")
                if not approval_id:
                    raise NodeExecutionError(node.id, "创建审批任务失败：未返回任务 ID")

                ctx.emit("node_log", nodeId=node.id, level="info",
                         message=f"等待人工审批 #{approval_id}：{title}")
                deadline = time.monotonic() + wait_seconds
                status = str(task.get("status") or "PENDING")
                comment = ""
                decided_by = None
                while status == "PENDING":
                    if time.monotonic() >= deadline:
                        raise NodeExecutionError(node.id, f"审批等待超时（{wait_seconds}s），请到「审批」页处理")
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    poll = await client.get(f"{base_url}/internal/approvals/{approval_id}", headers=headers)
                    poll.raise_for_status()
                    current = (poll.json() or {}).get("data") or {}
                    status = str(current.get("status") or "PENDING")
                    comment = str(current.get("comment") or "")
                    decided_by = current.get("decidedBy")
        except NodeExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - approval failures surface as node errors
            raise NodeExecutionError(node.id, f"人工审批失败: {exc}") from exc

        if status == "APPROVED":
            ctx.emit("node_log", nodeId=node.id, level="info", message=f"审批 #{approval_id} 已通过")
            return {
                "approved": True,
                "approvalId": approval_id,
                "status": status,
                "comment": comment,
                "decidedBy": decided_by,
                "text": comment or "已通过",
                "auto": False,
            }
        if status == "REJECTED":
            if reject_behavior == "continue":
                ctx.emit("node_log", nodeId=node.id, level="warn",
                         message=f"审批 #{approval_id} 被驳回，按配置继续")
                return {
                    "approved": False,
                    "approvalId": approval_id,
                    "status": status,
                    "comment": comment,
                    "decidedBy": decided_by,
                    "text": comment or "已驳回",
                    "auto": False,
                }
            raise NodeExecutionError(node.id, f"审批被驳回: {comment or '未填写原因'}")
        raise NodeExecutionError(node.id, f"审批任务已过期（{status}），请重新发起")
