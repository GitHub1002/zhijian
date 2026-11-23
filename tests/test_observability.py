"""请求级日志：request_id 透传，且日志不记录查询参数或正文。"""
import logging

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return TestClient(app)


def test_request_id_is_generated(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert len(response.headers["X-Request-ID"]) == 16


def test_request_id_is_echoed(client):
    response = client.get("/api/auth/me", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"


def test_access_log_has_no_query_or_body(client, caplog):
    caplog.set_level(logging.INFO, logger="app.request")

    client.get("/api/auth/me?q=secret-question")

    messages = [record.message for record in caplog.records if record.name == "app.request"]
    assert any('"path": "/api/auth/me"' in message for message in messages)
    assert all("secret-question" not in message for message in messages)
    assert all('"status": 401' in message for message in messages)
