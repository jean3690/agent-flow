from __future__ import annotations

from typing import Any


class BizError(Exception):
    def __init__(self, message: str, code: int = 4000, status: int = 400, data: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.data = data


def not_found(message: str) -> BizError:
    return BizError(message, 4040, 404)


def unauthorized(message: str) -> BizError:
    return BizError(message, 4010, 401)


def conflict(message: str) -> BizError:
    return BizError(message, 4090, 409)


def forbidden(message: str) -> BizError:
    return BizError(message, 4030, 403)
