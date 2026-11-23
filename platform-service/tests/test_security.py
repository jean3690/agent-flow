from __future__ import annotations

import time

import jwt
import pytest

from app.errors import BizError
from app.security import (
    CryptoService,
    CurrentUser,
    generate_api_key,
    hash_password,
    issue_token,
    mask_api_key,
    mask_secret,
    parse_token,
    verify_password,
)


def test_password_roundtrip():
    hashed = hash_password("admin123")
    assert hashed.startswith("$2")
    assert verify_password("admin123", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("admin123", "not-a-hash")


def test_jwt_roundtrip_and_invalid():
    token = issue_token(7, "alice", "ADMIN")
    user = parse_token(token)
    assert user == CurrentUser(7, "alice", "ADMIN")
    assert user.is_admin
    with pytest.raises(BizError):
        parse_token(token + "x")


def test_jwt_expired(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    payload = {"sub": "1", "username": "a", "role": "USER", "iat": int(time.time()) - 100, "exp": int(time.time()) - 10}
    expired = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(BizError):
        parse_token(expired)


def test_crypto_roundtrip_and_plaintext_passthrough():
    crypto = CryptoService("unit-test-key")
    cipher = crypto.encrypt("sk-secret-value")
    assert cipher.startswith("enc:v1:")
    assert cipher != "sk-secret-value"
    assert crypto.decrypt(cipher) == "sk-secret-value"
    assert crypto.encrypt("enc:v1:already") == "enc:v1:already"
    assert crypto.decrypt("plain") == "plain"


def test_api_key_shape_and_masking():
    raw = generate_api_key()
    assert raw.startswith("af_")
    assert len(raw) > 30
    assert mask_api_key(raw).startswith(raw[:6])
    assert mask_api_key("short") == "****"
    assert mask_secret("sk-123456") == "****3456"
    assert mask_secret("") == ""


def test_crypto_rejects_tampered_cipher():
    crypto = CryptoService("unit-test-key")
    cipher = crypto.encrypt("value")
    tampered = cipher[:-2] + ("AA" if not cipher.endswith("AA") else "BB")
    with pytest.raises(RuntimeError):
        crypto.decrypt(tampered)
