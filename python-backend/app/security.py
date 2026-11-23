from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

from .settings import settings

logger = logging.getLogger("paiagent.auth")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_PREFIX = "auth:refresh:"


class _MemoryRefreshStore:
    """Fallback refresh-token store used when Redis is unavailable."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = (value, time.time() + ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            value, expires_at = item
            if expires_at <= time.time():
                self._data.pop(key, None)
                return None
            return value

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)


class RefreshTokenStore:
    def __init__(self) -> None:
        self._memory = _MemoryRefreshStore()
        self._redis = None
        try:
            import redis

            client = redis.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password or None,
                socket_connect_timeout=1,
                socket_timeout=2,
                decode_responses=True,
            )
            client.ping()
            self._redis = client
            logger.info("Refresh token store: redis")
        except Exception as exc:  # pragma: no cover - depends on local infra
            logger.warning("Redis unavailable (%s), refresh tokens kept in memory", exc)

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if self._redis is not None:
            try:
                self._redis.set(key, value, ex=ttl_seconds)
                return
            except Exception:
                self._redis = None
        self._memory.set(key, value, ttl_seconds)

    def get(self, key: str) -> Optional[str]:
        if self._redis is not None:
            try:
                return self._redis.get(key)
            except Exception:
                self._redis = None
        return self._memory.get(key)

    def delete(self, key: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(key)
            except Exception:
                self._redis = None
        self._memory.delete(key)


class AuthService:
    def __init__(self) -> None:
        self.secret = settings.resolve_jwt_secret()
        secret_bytes = self.secret.encode("utf-8")
        if len(secret_bytes) < 32:
            # JJWT requires a 256-bit key; derive a compliant key from short input.
            import hashlib

            self.secret = hashlib.sha256(secret_bytes).hexdigest()
            secret_bytes = self.secret.encode("utf-8")
        # JJWT picks the strongest HMAC algorithm the key supports.
        if len(secret_bytes) >= 64:
            self.algorithm = "HS512"
        elif len(secret_bytes) >= 48:
            self.algorithm = "HS384"
        else:
            self.algorithm = "HS256"
        self.store = RefreshTokenStore()

    @staticmethod
    def _key(refresh_token: str) -> str:
        return REFRESH_TOKEN_PREFIX + refresh_token

    def login(self, username: str, password: str) -> Optional[dict]:
        expected_username = (settings.default_username or "").strip()
        expected_password = (settings.default_password or "").strip()
        if expected_username and expected_password:
            if expected_username == username and expected_password == password:
                return self._issue_tokens(username)
        return None

    def refresh(self, refresh_token: str) -> Optional[dict]:
        username = self.username_by_refresh_token(refresh_token)
        if not username:
            return None
        self.revoke_refresh_token(refresh_token)
        return self._issue_tokens(username)

    def logout(self, refresh_token: Optional[str]) -> None:
        self.revoke_refresh_token(refresh_token)

    def _issue_tokens(self, username: str) -> dict:
        access_token = self._create_access_token(username)
        refresh_token = uuid.uuid4().hex
        ttl = settings.refresh_token_expiration_hours * 3600
        self.store.set(self._key(refresh_token), username, ttl)
        return {"token": access_token, "refreshToken": refresh_token, "user": {"username": username}}

    def _create_access_token(self, username: str) -> str:
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + timedelta(minutes=settings.access_token_expiration_minutes)
        payload = {
            "sub": username,
            "tokenType": ACCESS_TOKEN_TYPE,
            "iat": issued_at,
            "exp": expires_at,
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def _claims(self, token: str) -> Optional[dict]:
        try:
            return jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options={"verify_aud": False},
            )
        except Exception:
            return None

    def validate_token(self, token: str) -> bool:
        claims = self._claims(token)
        return bool(claims and claims.get("tokenType") == ACCESS_TOKEN_TYPE)

    def username_by_token(self, token: str) -> Optional[str]:
        claims = self._claims(token)
        if not claims or claims.get("tokenType") != ACCESS_TOKEN_TYPE:
            return None
        subject = claims.get("sub")
        return subject if isinstance(subject, str) else None

    def username_by_refresh_token(self, refresh_token: Optional[str]) -> Optional[str]:
        if not refresh_token:
            return None
        return self.store.get(self._key(refresh_token))

    def revoke_refresh_token(self, refresh_token: Optional[str]) -> None:
        if not refresh_token:
            return
        self.store.delete(self._key(refresh_token))


auth_service = AuthService()
