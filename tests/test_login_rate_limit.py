"""登录失败限流：窗口内超过次数后 429，成功后重置。"""
import pytest
from fastapi.testclient import TestClient

from app import config, db, rate_limit
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(config, "LOGIN_WINDOW_SECONDS", 60)
    db.init_db()
    db.create_user("alice", "secret123")
    rate_limit.clear()
    yield TestClient(app)
    rate_limit.clear()


def test_login_blocks_after_failures(client):
    for _ in range(2):
        assert client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong123"}
        ).status_code == 401

    blocked = client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong123"}
    )
    assert blocked.status_code == 429
    assert "尝试过多" in blocked.json()["detail"]


def test_successful_login_resets_failures(client):
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong123"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    ).status_code == 200

    # 成功登录后重新计数，仍允许再试一次错误密码
    assert client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrong123"}
    ).status_code == 401
