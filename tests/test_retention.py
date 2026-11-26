"""保留期清理：只删旧轨迹/点击/审计/归档记忆，不动反馈。"""
from datetime import datetime, timedelta, timezone

import pytest

from app import audit, db, retention, tracing


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _old():
    return (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()


def test_cleanup_dry_run_and_delete(temp_db):
    user = temp_db.create_user("alice", "secret123")
    old = _old()

    old_answer = temp_db.create_answer(user["id"], "旧问题", "旧回答", "[]")
    new_answer = temp_db.create_answer(user["id"], "新问题", "新回答", "[]")
    for answer_id in (old_answer, new_answer):
        tracing.record(
            answer_id=answer_id, user_id=user["id"], question="q", grounded=True
        )
    temp_db.record_source_click(old_answer, user["id"], "old.md")
    temp_db.record_source_click(new_answer, user["id"], "new.md")
    audit.log(user["id"], "feedback.triage", "feedback", 1)

    temp_db.save_feedback(
        old_answer, user["id"], sentiment="negative", reasons=["wrong_info"]
    )

    with temp_db.connect() as conn:
        conn.execute(
            "UPDATE answer_traces SET created_at = ? WHERE answer_id = ?",
            (old, old_answer),
        )
        conn.execute(
            "UPDATE source_clicks SET created_at = ? WHERE answer_id = ?",
            (old, old_answer),
        )
        conn.execute("UPDATE admin_audit_log SET created_at = ?", (old,))
        conn.execute(
            """CREATE TABLE legacy_assistant_memory (
                user_id INTEGER PRIMARY KEY,
                summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO legacy_assistant_memory(user_id, summary, updated_at) VALUES (?, ?, ?)",
            (user["id"], "旧摘要", old),
        )

    dry = retention.cleanup(dry_run=True)
    assert dry["answer_traces"] == 1
    assert dry["source_clicks"] == 1
    assert dry["admin_audit_log"] == 1
    assert dry["legacy_assistant_memory"] == 1

    with temp_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM answer_traces").fetchone()["n"] == 2

    retention.cleanup()

    with temp_db.connect() as conn:
        traces = conn.execute(
            "SELECT answer_id FROM answer_traces ORDER BY answer_id"
        ).fetchall()
        clicks = conn.execute("SELECT answer_id FROM source_clicks").fetchall()
        audit_count = conn.execute("SELECT COUNT(*) AS n FROM admin_audit_log").fetchone()["n"]
        legacy_count = conn.execute(
            "SELECT COUNT(*) AS n FROM legacy_assistant_memory"
        ).fetchone()["n"]
        feedback_count = conn.execute("SELECT COUNT(*) AS n FROM feedback").fetchone()["n"]

    assert [row["answer_id"] for row in traces] == [new_answer]
    assert [row["answer_id"] for row in clicks] == [new_answer]
    assert audit_count == 0
    assert legacy_count == 0
    assert feedback_count == 1
