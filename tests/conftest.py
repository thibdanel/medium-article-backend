import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-secret")
    from app.main import app

    app.state.public_rate_limits.clear()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": os.getenv("API_KEY", "test-secret")}
