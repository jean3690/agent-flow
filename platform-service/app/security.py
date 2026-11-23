from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.errors import unauthorized

API_KEY_PREFIX = "af_"
CIPHER_PREFIX = "enc:v1:"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return (self.role or "").upper() == "ADMIN"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def issue_token(user_id: int, username: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def parse_token(token: str) -> CurrentUser:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return CurrentUser(int(payload["sub"]), str(payload.get("username") or ""), str(payload.get("role") or "USER"))
    except Exception as exc:
        raise unauthorized("token 无效或已过期") from exc


class CryptoService:
    """AES-256-GCM，密文带 enc:v1: 前缀；历史明文原样返回。"""

    def __init__(self, key: str | None = None) -> None:
        raw = (key if key is not None else get_settings().crypto_key).encode("utf-8")
        self._aes = AESGCM(hashlib.sha256(raw).digest())

    def encrypt(self, plain: str | None) -> str | None:
        if plain is None or not plain.strip() or plain.startswith(CIPHER_PREFIX):
            return plain
        nonce = secrets.token_bytes(12)
        cipher_text = self._aes.encrypt(nonce, plain.encode("utf-8"), None)
        return CIPHER_PREFIX + base64.b64encode(nonce + cipher_text).decode("ascii")

    def decrypt(self, stored: str | None) -> str | None:
        if stored is None or not stored.startswith(CIPHER_PREFIX):
            return stored
        try:
            data = base64.b64decode(stored[len(CIPHER_PREFIX) :])
            return self._aes.decrypt(data[:12], data[12:], None).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("Key 解密失败（加密密钥是否变更过？）") from exc


def generate_api_key() -> str:
    return API_KEY_PREFIX + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def mask_api_key(raw: str) -> str:
    if not raw or len(raw) < 12:
        return "****"
    return raw[:6] + "****" + raw[-4:]


def mask_secret(raw: str | None) -> str:
    if not raw:
        return ""
    if len(raw) <= 4:
        return "****"
    return "****" + raw[-4:]


def hmac_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
