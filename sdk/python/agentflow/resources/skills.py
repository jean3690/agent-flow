from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from ..client import AgentFlowClient


def _skill_path(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("invalid skill identifier")
    return "/api/skills/" + quote(name, safe="")


class SkillResource:
    def __init__(self, client: AgentFlowClient) -> None:
        self._c = client

    def list(self) -> Any:
        return self._c.request("GET", "/api/skills")

    def get(self, name: str) -> Any:
        return self._c.request("GET", _skill_path(name))

    def reload(self) -> Any:
        return self._c.request("POST", "/api/skills/reload")

    def save(self, name: str, content: str) -> Any:
        """Create/update a custom SKILL.md; requires an administrator account."""
        return self._c.request("PUT", _skill_path(name), json={"content": content})

    def delete(self, name: str) -> Any:
        return self._c.request("DELETE", _skill_path(name))

    def reference(self, name: str, file: str) -> Any:
        if not isinstance(file, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\.md", file):
            raise ValueError("invalid Markdown reference filename")
        return self._c.request("GET", _skill_path(name) + "/references/" + quote(file, safe=""))
