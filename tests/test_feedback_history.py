"""反馈详情：修改历史和分诊历史。"""
import pytest

from app import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def test_feedback_detail_includes_history(temp_db):
    user = temp_db.create_user("alice", "secret123")
    admin = temp_db.create_user("admin", "secret123", role="admin")
    answer_id = temp_db.create_answer(user["id"], "年假多少天", "5 天", "[]")
    feedback_id = temp_db.save_feedback(
        answer_id,
        user["id"],
        sentiment="negative",
        reasons=["wrong_info"],
        comment="旧评论",
    )
    temp_db.update_feedback(
        feedback_id,
        user["id"],
        sentiment="negative",
        reasons=["incomplete"],
        comment="新评论",
    )
    temp_db.triage_feedback(
        feedback_id, admin["id"], "resolved", "generation_failure", "已处理"
    )

    detail = temp_db.feedback_detail(feedback_id)

    assert len(detail["revisions"]) == 1
    revision = detail["revisions"][0]
    assert revision["actor_name"] == "alice"
    assert revision["snapshot"]["comment"] == "旧评论"
    assert revision["snapshot"]["reasons"] == ["wrong_info"]

    assert len(detail["triage_events"]) == 1
    event = detail["triage_events"][0]
    assert event["actor_name"] == "admin"
    assert event["from_status"] == "new"
    assert event["to_status"] == "resolved"
    assert event["category"] == "generation_failure"
    assert event["note"] == "已处理"
