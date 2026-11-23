from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from .. import mcp
from ..db import get_db
from ..result import error, success

router = APIRouter(prefix="/api/mcp-tools", tags=["MCP 工具管理接口"])


@router.get("")
def list_tools(db: Session = Depends(get_db)):
    return success(mcp.list_configs(db))


@router.post("")
def create_tool(payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        return success(mcp.create_config(db, payload or {}))
    except Exception as exc:
        return error(str(exc))


@router.post("/agent-plan-web-search")
def create_agent_plan_web_search(payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        return success(mcp.create_agent_plan_web_search(db, payload or {}))
    except Exception as exc:
        return error(str(exc))


@router.put("/{config_id}")
def update_tool(config_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        return success(mcp.update_config(db, config_id, payload or {}))
    except Exception as exc:
        return error(str(exc))


@router.delete("/{config_id}")
def delete_tool(config_id: int, db: Session = Depends(get_db)):
    mcp.delete_config(db, config_id)
    return success()


@router.post("/{config_id}/test")
def test_tool(config_id: int, payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    try:
        query = (payload or {}).get("query")
        return success(mcp.test_config(db, config_id, query))
    except Exception as exc:
        return error(str(exc))
