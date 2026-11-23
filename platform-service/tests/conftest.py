from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DB_PATH = Path("/tmp/agentflow-platform-test.db")
for suffix in ("", "-wal", "-shm"):
    candidate = Path(str(DB_PATH) + suffix)
    if candidate.exists():
        candidate.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["APP_AUTH_DEFAULT_USERNAME"] = "admin"
os.environ["APP_AUTH_DEFAULT_PASSWORD"] = "admin123"
os.environ["JWT_SECRET"] = "test-secret-key-for-platform-service"
os.environ["CRYPTO_KEY"] = "test-crypto-key"
os.environ["AI_INTERNAL_TOKEN"] = "test-internal-token"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def token(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert response.status_code == 200
    return response.json()["data"]["token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def simple_flow():
    return {
        "nodes": [
            {"id": "in", "type": "input", "config": {"variables": ["topic"]}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"id": "e1", "source": "in", "target": "out"}],
    }


@pytest.fixture()
def workflow(client, auth, simple_flow):
    response = client.post("/api/workflows", headers=auth, json={"name": "测试工作流", "flow": simple_flow})
    assert response.status_code == 200, response.text
    return response.json()["data"]
