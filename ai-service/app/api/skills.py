from __future__ import annotations

from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.errors import SkillNotFoundError
from app.skills.registry import get_skill_registry

router = APIRouter(prefix="/v1/skills", tags=["skills"])


def require_internal(x_internal_token: str = Header(default="")):
    expected = get_settings().internal_token
    if not expected or not compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=403, detail="仅允许平台服务管理技能")


class SkillSaveRequest(BaseModel):
    content: str = Field(max_length=200_000)


@router.put("/{name}", dependencies=[Depends(require_internal)])
async def save_skill(name: str, request: SkillSaveRequest):
    try:
        return {"data": get_skill_registry().save(name, request.content)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{name}", dependencies=[Depends(require_internal)])
async def delete_skill(name: str):
    try:
        get_skill_registry().delete(name)
        return {"data": None}
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
async def list_skills():
    return {"data": get_skill_registry().summary()}


@router.post("/reload", dependencies=[Depends(require_internal)])
async def reload_skills():
    registry = get_skill_registry()
    registry.reload()
    return {"data": registry.summary()}


@router.get("/{name}")
async def skill_detail(name: str):
    try:
        return {"data": get_skill_registry().detail(name)}
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.get("/{name}/references/{reference}")
async def skill_reference(name: str, reference: str):
    try:
        return {"data": get_skill_registry().reference(name, reference)}
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
