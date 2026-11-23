from __future__ import annotations

from fastapi import APIRouter

from ..result import error, success
from ..skills import skill_registry

router = APIRouter(prefix="/api/skills", tags=["技能接口"])


@router.get("")
def list_skills():
    return success(skill_registry.get_skill_summaries())


@router.get("/{skill_name}/references/{reference_name}")
def get_skill_reference(skill_name: str, reference_name: str):
    try:
        return success(skill_registry.load_reference(skill_name, reference_name))
    except Exception:
        return error(f"Reference not found: {skill_name}/{reference_name}", 404)


@router.get("/{name}")
def get_skill(name: str):
    skill = skill_registry.get_skill(name)
    if skill is None:
        return error(f"Skill not found: {name}", 404)
    return success(
        {
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "references": skill.references,
        }
    )
