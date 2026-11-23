from __future__ import annotations

from fastapi import APIRouter, Request

from app.errors import BizError
from app.http import current_user
from app.serialization import ok
from app.services.skills import SkillService

router = APIRouter(prefix="/api/skills", tags=["skills"])
service = SkillService()


@router.get("")
def list_skills():
    return ok(service.list_skills())


@router.post("/reload")
def reload_skills(request: Request):
    user = current_user(request)
    return ok(service.reload(user))


@router.get("/{name}")
def skill_detail(name: str):
    return ok(service.detail(name))


@router.put("/{name}")
def save_skill(name: str, request: Request):
    user = current_user(request)
    payload = request.state.body or {}
    content = payload.get("content")
    if not isinstance(content, str) or len(content) > 200_000:
        raise BizError("content 不能为空且不能超过 200000 字符")
    return ok(service.save(name, content, user))


@router.delete("/{name}")
def delete_skill(name: str, request: Request):
    user = current_user(request)
    service.delete(name, user)
    return ok()


@router.get("/{name}/references/{file}")
def skill_reference(name: str, file: str):
    return ok(service.reference(name, file))
