from typing import Any

from app.core.errors import NodeExecutionError
from app.graph.context import NodeContext
from app.graph.state import FlowState
from app.mcp_client import call_tool
from app.nodes.base import NodeExecutor
from app.nodes.registry import register
from app.nodes.value_utils import names_for, parse_json, render_deep
from app.schemas.flow import FlowNode


@register
class McpToolNodeExecutor(NodeExecutor):
    type = "mcp_tool"

    async def execute(self, node: FlowNode, state: FlowState, ctx: NodeContext) -> dict[str, Any]:
        server_id = str(node.config.get("serverId") or "")
        server = ctx.mcp_servers.get(server_id)
        tool = str(node.config.get("toolName") or "")
        if not server or tool not in server.allowed_tools:
            raise NodeExecutionError(node.id, "MCP 服务或工具未授权 / 已禁用")
        arguments = render_deep(parse_json(node.config.get("arguments", "{}")), names_for(state))
        if not isinstance(arguments, dict):
            raise NodeExecutionError(node.id, "MCP 参数必须是 JSON 对象")
        try:
            result = await call_tool(server, tool, arguments, ctx.settings)
        except Exception as exc:
            raise NodeExecutionError(node.id, "MCP 调用失败：请检查服务状态、授权工具和参数") from exc
        return {**result, "serverId": server_id, "toolName": tool}
