from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import unauthorized
from app.models import User
from app.security import CurrentUser, issue_token, verify_password


def user_vo(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "role": user.role,
        "avatar": user.avatar,
    }


def login(session: Session, username: str, password: str) -> dict:
    user = session.scalar(select(User).where(User.username == username, User.deleted == 0))
    if user is None or not verify_password(password, user.password):
        raise unauthorized("用户名或密码错误")
    return {"token": issue_token(user.id, user.username, user.role), "user": user_vo(user)}


def current(session: Session, user: CurrentUser) -> dict:
    entity = session.scalar(select(User).where(User.id == user.id, User.deleted == 0))
    if entity is None:
        raise unauthorized("用户不存在")
    return user_vo(entity)
