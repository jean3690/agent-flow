from fastapi import APIRouter, Depends

from app.api.skills import require_internal
from app.config import get_settings
from app.mcp_client import McpServerConfig, discover_tools

router = APIRouter(prefix="/v1/mcp", tags=["mcp"], dependencies=[Depends(require_internal)])


@router.post("/discover")
async def discover(config: McpServerConfig):
    try:
        tools = await discover_tools(config, get_settings())
        return {"data": {"ok": True, "tools": tools, "message": f"连接成功，发现 {len(tools)} 个工具"}}
    except Exception:  # noqa: BLE001 - sanitize third-party protocol/transport failures
        # MCP/provider exception messages may contain credentials or full URLs.
        return {"data": {"ok": False, "tools": [], "message": "连接失败：请检查地址、认证、超时和部署端内网白名单"}}
