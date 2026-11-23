from __future__ import annotations

import re
from typing import Any

from app.ai_client import AiClient, get_ai
from app.errors import BizError, forbidden
from app.security import CurrentUser

NAME_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
FILE_PATTERN = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}\.md")


class SkillService:
    def __init__(self, ai: AiClient | None = None) -> None:
        self.ai = ai or get_ai()

    def list_skills(self) -> list[Any]:
        return self.ai.data_list("/v1/skills")

    def detail(self, name: str) -> Any:
        self._name(name)
        return self.ai.data("/v1/skills/" + name)

    def save(self, name: str, content: str, user: CurrentUser) -> Any:
        self._admin(user)
        self._name(name)
        return self.ai.put_json("/v1/skills/" + name, {"content": content}).get("data")

    def delete(self, name: str, user: CurrentUser) -> None:
        self._admin(user)
        self._name(name)
        self.ai.delete("/v1/skills/" + name)

    def reference(self, name: str, file: str) -> Any:
        self._name(name)
        if not FILE_PATTERN.fullmatch(file):
            raise BizError("引用文件名无效")
        return self.ai.data(f"/v1/skills/{name}/references/{file}")

    def reload(self, user: CurrentUser) -> Any:
        self._admin(user)
        return self.ai.post_empty("/v1/skills/reload").get("data")

    @staticmethod
    def _name(name: str | None) -> None:
        if not name or not NAME_PATTERN.fullmatch(name):
            raise BizError("技能标识无效")

    @staticmethod
    def _admin(user: CurrentUser) -> None:
        if not user.is_admin:
            raise forbidden("只有管理员可管理平台共享技能")
