from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.errors import SkillNotFoundError
from app.skills.registry import get_skill_registry

router = APIRouter(prefix="/v1/skills", tags=["skills"])


@router.get("")
async def list_skills():
    return {"data": get_skill_registry().summary()}


@router.post("/reload")
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
