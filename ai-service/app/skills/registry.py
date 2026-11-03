from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings
from app.core.errors import SkillNotFoundError


@dataclass
class Skill:
    name: str
    title: str
    description: str
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None

    @property
    def root(self) -> Path | None:
        return self.path.parent if self.path else None

    def summary(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
        }

    def references(self) -> list[dict]:
        if not self.root:
            return []
        ref_dir = self.root / "references"
        if not ref_dir.is_dir():
            return []
        return [
            {"name": item.stem, "file": item.name, "size": item.stat().st_size}
            for item in sorted(ref_dir.glob("*.md"))
        ]


def _parse_skill(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            meta = yaml.safe_load(parts[1]) or {}
            body = parts[2].lstrip("\n")
    name = str(meta.get("name") or path.parent.name)
    return Skill(
        name=name,
        title=str(meta.get("title") or name),
        description=str(meta.get("description") or ""),
        version=str(meta.get("version") or "1.0.0"),
        tags=list(meta.get("tags") or []),
        body=body,
        path=path,
    )


class SkillRegistry:
    """Level 1: summary list, Level 2: full SKILL.md, Level 3: references/*.md."""

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or get_settings().skills_dir)
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            skills: dict[str, Skill] = {}
            if self.directory.is_dir():
                for path in sorted(self.directory.glob("*/SKILL.md")):
                    try:
                        skill = _parse_skill(path)
                    except Exception:  # noqa: BLE001 - a broken skill must not break startup
                        continue
                    skills[skill.name] = skill
            self._skills = skills

    def summary(self) -> list[dict]:
        return [skill.summary() for skill in self._skills.values()]

    def names(self) -> list[str]:
        return sorted(self._skills)

    def detail(self, name: str) -> dict:
        skill = self._skills.get(name) or self._skills.get(name.lower())
        if not skill:
            raise SkillNotFoundError(f"技能不存在: {name}")
        payload = skill.summary()
        payload["content"] = skill.body
        payload["references"] = skill.references()
        return payload

    def reference(self, name: str, reference: str) -> dict:
        skill = self._skills.get(name)
        if not skill or not skill.root:
            raise SkillNotFoundError(f"技能不存在: {name}")
        target = (skill.root / "references" / reference).resolve()
        if not target.is_file() or skill.root.resolve() not in target.parents:
            raise SkillNotFoundError(f"引用文档不存在: {reference}")
        return {"name": reference, "content": target.read_text(encoding="utf-8")}


_registry: SkillRegistry | None = None
_registry_lock = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = SkillRegistry()
    return _registry
