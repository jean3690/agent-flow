from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from .. import llm_config_service
from ..db import get_db
from ..result import error, success

router = APIRouter(prefix="/api/llm-config", tags=["全局模型配置接口"])


@router.get("/detail/{config_id}")
def get_by_id(config_id: int, db: Session = Depends(get_db)):
    config = llm_config_service.get_by_id(db, config_id)
    if config is None:
        return error("配置不存在")
    return success(llm_config_service.llm_config_to_dict(config))


@router.get("/default/{provider}")
def get_default(provider: str, db: Session = Depends(get_db)):
    config = llm_config_service.get_default_config(db, provider)
    return success(llm_config_service.llm_config_to_dict(config) if config else None)


@router.get("/{provider}")
def list_by_provider(provider: str, db: Session = Depends(get_db)):
    configs = llm_config_service.list_by_provider(db, provider)
    return success([llm_config_service.llm_config_to_dict(config) for config in configs])


@router.get("")
def list_all(db: Session = Depends(get_db)):
    configs = llm_config_service.list_all(db)
    return success([llm_config_service.llm_config_to_dict(config) for config in configs])


@router.post("")
def save_config(payload: Optional[dict] = Body(default=None), db: Session = Depends(get_db)):
    payload = payload or {}
    try:
        config = llm_config_service.save_config(db, payload)
        return success(llm_config_service.llm_config_to_dict(config))
    except ValueError as exc:
        message = str(exc)
        if message == "同一供应商下的配置别名不能重复":
            return error("保存配置失败: 同一供应商下的配置别名不能重复")
        return error(f"保存配置失败: {message}")
    except Exception:
        db.rollback()
        return error("保存配置失败，请稍后重试")


@router.delete("/{config_id}")
def delete_config(config_id: int, db: Session = Depends(get_db)):
    llm_config_service.delete_config(db, config_id)
    return success()


@router.post("/{config_id}/default")
def set_default(config_id: int, db: Session = Depends(get_db)):
    try:
        llm_config_service.set_default_config(db, config_id)
        return success()
    except Exception as exc:
        db.rollback()
        return error(f"设置默认配置失败: {exc}")
