from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.config import get_settings
from app.core.errors import SkillNotFoundError

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
MAX_SKILL_CHARS = 200_000
logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    title: str
    description: str
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None
    managed: bool = False

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
            "editable": self.managed,
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


def _parse_content(raw: str, fallback_name: str) -> Skill:
    meta: dict = {}
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as exc:
                raise ValueError("技能 Frontmatter 不是合法 YAML") from exc
            body = parts[2].lstrip("\n")
    if not isinstance(meta, dict):
        raise TypeError("SKILL.md 的 Frontmatter 必须是 YAML 对象")
    if not isinstance(meta.get("tags", []), list):
        raise TypeError("tags 必须是字符串数组")
    name = str(meta.get("name") or fallback_name)
    return Skill(
        name=name,
        title=str(meta.get("title") or name),
        description=str(meta.get("description") or ""),
        version=str(meta.get("version") or "1.0.0"),
        tags=list(meta.get("tags") or []),
        body=body,
    )


def _parse_skill(path: Path) -> Skill:
    skill = _parse_content(path.read_text(encoding="utf-8"), path.parent.name)
    skill.path = path
    return skill


class SkillRegistry:
    """Level 1: summary list, Level 2: full SKILL.md, Level 3: references/*.md."""

    def __init__(self, directory: Path | None = None, managed_directory: Path | None = None):
        self.directory = Path(directory or get_settings().skills_dir)
        self.managed_directory = Path(managed_directory) if managed_directory is not None else (
            Path(get_settings().managed_skills_dir) if directory is None else None
        )
        self._skills: dict[str, Skill] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        with self._lock:
            skills: dict[str, Skill] = {}
            for directory, managed in ((self.directory, False), (self.managed_directory, True)):
                if directory is None or not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*/SKILL.md")):
                    if path.is_symlink() or path.parent.is_symlink():
                        continue
                    try:
                        skill = _parse_skill(path)
                    except Exception:  # noqa: BLE001 - a broken skill must not break startup
                        logger.warning("跳过无法解析的技能: %s", path.parent.name)
                        continue
                    if skill.name in skills:
                        continue
                    skill.managed = managed
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
        payload["rawContent"] = skill.path.read_text(encoding="utf-8") if skill.path else skill.body
        payload["references"] = skill.references()
        return payload

    def save(self, name: str, raw: str) -> dict:
        if not _NAME.fullmatch(name) or not self.managed_directory:
            raise ValueError("技能名称须为小写字母开头，包含字母、数字、下划线或连字符，最多 64 字符")
        if len(raw) > MAX_SKILL_CHARS or not raw.startswith("---"):
            raise ValueError("SKILL.md 需包含 YAML Frontmatter，且不能超过 200,000 字符")
        skill = _parse_content(raw, name)
        if skill.name != name or not skill.description.strip() or not skill.body.strip():
            raise ValueError("name 必须与技能标识一致，description 和正文不能为空")
        if len(skill.title) > 128 or len(skill.description) > 2000 or len(skill.version) > 32:
            raise ValueError("技能标题、描述或版本过长")
        if len(skill.tags) > 20 or not all(isinstance(tag, str) and len(tag) <= 64 for tag in skill.tags):
            raise ValueError("tags 必须是最多 20 个短字符串组成的数组")
        with self._lock:
            existing = self._skills.get(name)
            if existing and not existing.managed:
                raise ValueError("内置技能只读，请使用新的技能标识创建副本")
            root = self.managed_directory.resolve()
            folder = root / name
            if folder.is_symlink() or (folder / "SKILL.md").is_symlink():
                raise ValueError("不允许通过符号链接写入技能")
            folder.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=folder, delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(raw)
                os.replace(temporary, folder / "SKILL.md")
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
            skill.path = folder / "SKILL.md"
            skill.managed = True
            self._skills = {**self._skills, name: skill}
        return self.detail(name)

    def delete(self, name: str) -> None:
        with self._lock:
            skill = self._skills.get(name)
            if not skill:
                raise SkillNotFoundError(f"技能不存在: {name}")
            if not skill.managed or not skill.path or skill.path.is_symlink() or skill.path.parent.is_symlink():
                raise ValueError("内置技能只读或路径不安全")
            skill.path.unlink()
            self._skills = {key: value for key, value in self._skills.items() if key != name}

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
