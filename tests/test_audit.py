"""管理端审计：记录动作、筛选，且不落评论正文。"""
import json

import pytest
from fastapi.testclient import TestClient

from app import audit, db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.create_user("admin", "secret123", role="admin")
    db.create_user("alice", "secret123")
    return TestClient(app)


def test_audit_log_filters(client):
    with db.connect() as conn:
        admin_id = conn.execute(
            "SELECT id FROM users WHERE username = 'admin'"
        ).fetchone()["id"]

    audit.log(admin_id, "feedback.triage", "feedback", 1, {"status": "resolved"})
    audit.log(admin_id, "experiment.update", "experiment", "demo", {"status": "paused"})

    page = audit.list_events(action="feedback.triage")
    assert page["total"] == 1
    assert page["items"][0]["detail"] == {"status": "resolved"}
    assert audit.list_events(target_type="experiment")["total"] == 1


def test_admin_actions_are_audited(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).status_code == 200

    created = client.post(
        "/api/admin/content-tasks",
        json={"title": "补充年假文档", "kind": "doc_fix", "priority": "high"},
    )
    assert created.status_code == 200, created.text

    page = client.get("/api/admin/audit-log?action=content_task.create")
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1
    assert page.json()["items"][0]["target_type"] == "content_task"


def test_audit_detail_does_not_contain_comment(client):
    with db.connect() as conn:
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = 'alice'"
        ).fetchone()["id"]
    answer_id = db.create_answer(user_id, "年假多少天", "5 天", "[]")
    feedback_id = db.save_feedback(
        answer_id, user_id, sentiment="negative",
        reasons=["wrong_info"], comment="secret-comment",
    )

    assert client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).status_code == 200
    triaged = client.patch(
        f"/api/admin/feedback/{feedback_id}",
        json={"status": "resolved", "category": "generation_failure", "note": "ok"},
    )
    assert triaged.status_code == 200, triaged.text

    page = client.get("/api/admin/audit-log?action=feedback.triage").json()
    assert page["total"] == 1
    detail = json.dumps(page["items"][0]["detail"], ensure_ascii=False)
    assert "secret-comment" not in detail


def test_audit_log_requires_admin(client):
    assert client.post("/api/auth/login", json={"username": "alice", "password": "secret123"}).status_code == 200
    assert client.get("/api/admin/audit-log").status_code == 403
