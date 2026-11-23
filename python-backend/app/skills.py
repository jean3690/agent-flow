from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .settings import settings

logger = logging.getLogger("paiagent.skills")

FRONTMATTER_RE = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$")
SAFE_REFERENCE_NAME = re.compile(r"^[a-zA-Z0-9._-]+$")


class Skill:
    def __init__(self, name: str, description: str, content: str, skill_path: Optional[Path], references: list[str]):
        self.name = name
        self.description = description
        self.content = content
        self.skill_path = skill_path
        self.references = references

    def summary(self) -> str:
        parts = [f"# 技能: {self.name}\n\n", f"{self.description}\n\n", "---\n\n", "## 技能指南\n\n", f"{self.content}\n\n"]
        if self.references:
            parts.append("## 可用参考文档\n")
            parts.append("调用 load_skill_reference 函数获取：\n")
            for ref in self.references:
                parts.append(f"- {ref}\n")
        return "".join(parts)

    def full_content(self) -> str:
        parts = [f"# {self.name}\n\n", f"{self.content}\n\n"]
        if self.references:
            parts.append("## 可用的参考文档\n")
            for ref in self.references:
                parts.append(f"- {ref}\n")
            parts.append("\n调用 load_skill_reference 函数获取详细内容。\n")
        return "".join(parts)

    def full_execution_prompt(self, reference_contents: dict[str, str]) -> str:
        parts = [
            f"# 技能: {self.name}\n\n",
            f"{self.description}\n\n",
            "---\n\n",
            "## 技能指南\n\n",
            f"{self.content}\n\n",
        ]
        if reference_contents:
            parts.append("## 参考文档\n\n")
            for name, body in reference_contents.items():
                parts.append(f"### {name}\n\n")
                parts.append(f"{body}\n\n")
        return "".join(parts)


def _parse_frontmatter(raw: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        metadata[key.strip()] = value
    return metadata


class SkillRegistry:
    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}
        self.reference_cache: dict[str, dict[str, str]] = {}
        self.skills_path = settings.resolve_skills_path()
        self._load()

    def _load(self) -> None:
        if not self.skills_path.is_dir():
            logger.warning("Skills directory not found: %s", self.skills_path)
            return
        for skill_dir in sorted(p for p in self.skills_path.iterdir() if p.is_dir()):
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                self._register_dir(skill_dir, skill_file)
            except Exception as exc:
                logger.warning("Failed to load skill from %s: %s", skill_dir, exc)
        logger.info("Loaded %d skill(s) from %s", len(self.skills), self.skills_path)

    def _register_dir(self, skill_dir: Path, skill_file: Path) -> None:
        raw = skill_file.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(raw)
        if not match:
            raise ValueError(f"Invalid SKILL.md format: missing YAML frontmatter in {skill_file}")
        metadata = _parse_frontmatter(match.group(1))
        name = metadata.get("name")
        if not name:
            raise ValueError(f"Skill name is required in frontmatter: {skill_file}")
        content = match.group(2).strip()
        reference_dir = skill_dir / "reference"
        references: list[str] = []
        if reference_dir.is_dir():
            references = sorted(
                p.stem for p in reference_dir.iterdir() if p.is_file() and p.name.endswith(".md")
            )
        self.skills[name] = Skill(name, metadata.get("description", ""), content, skill_dir, references)
        cache: dict[str, str] = {}
        for ref in references:
            try:
                cache[ref] = (reference_dir / f"{ref}.md").read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed to read reference %s/%s: %s", name, ref, exc)
        if cache:
            self.reference_cache[name] = cache

    def get_skill(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_skill_summaries(self) -> list[dict]:
        return [
            {"name": skill.name, "description": skill.description}
            for skill in sorted(self.skills.values(), key=lambda item: item.name)
        ]

    def load_reference(self, skill_name: str, reference_name: str) -> str:
        skill = self.skills.get(skill_name)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_name}")
        if not reference_name:
            raise ValueError("Reference name is required")
        if not SAFE_REFERENCE_NAME.match(reference_name):
            raise ValueError(f"Invalid reference name: {reference_name}")
        if reference_name not in skill.references:
            raise ValueError(f"Reference not found in skill: {reference_name}")
        cached = self.reference_cache.get(skill_name, {}).get(reference_name)
        if cached is not None:
            return cached
        if skill.skill_path is None:
            raise ValueError("Skill path is not available")
        reference_dir = (skill.skill_path / "reference").resolve()
        reference_file = (reference_dir / f"{reference_name}.md").resolve()
        if reference_dir not in reference_file.parents:
            raise ValueError(f"Invalid reference path: {reference_name}")
        if not reference_file.is_file():
            raise ValueError(f"Reference file not found: {reference_file}")
        content = reference_file.read_text(encoding="utf-8")
        self.reference_cache.setdefault(skill_name, {})[reference_name] = content
        return content

    def load_all_references(self, skill_name: str) -> dict[str, str]:
        skill = self.skills.get(skill_name)
        if skill is None:
            return {}
        cached = self.reference_cache.get(skill_name)
        if cached:
            return dict(cached)
        references: dict[str, str] = {}
        for ref in skill.references:
            try:
                references[ref] = self.load_reference(skill_name, ref)
            except Exception as exc:
                logger.warning("Failed to load reference %s/%s: %s", skill_name, ref, exc)
        if references:
            self.reference_cache[skill_name] = dict(references)
        return references


skill_registry = SkillRegistry()
