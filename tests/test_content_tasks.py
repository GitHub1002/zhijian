"""内容任务：从负反馈归因、去重、状态流转。"""
import json

import pytest

from app import content, content_store, db

SOURCES = [
    {
        "index": 1,
        "source": "hr/leave.md",
        "heading": "年假",
        "library": "hr",
    }
]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _feedback(database, username="alice", reasons=None, marks=None, rating=1):
    user = database.create_user(username, "secret123")
    answer_id = database.create_answer(
        user["id"], "年假多少天", "5 天", json.dumps(SOURCES, ensure_ascii=False)
    )
    feedback_id = database.save_feedback(
        answer_id,
        user["id"],
        rating,
        sentiment="positive" if rating >= 5 else "negative",
        reasons=reasons or ["wrong_info"],
        comment="答案不对",
        source_marks=marks,
    )
    return user, feedback_id


def test_build_task_uses_source_mark_and_trace_rules(temp_db):
    _, feedback_id = _feedback(
        temp_db, reasons=["wrong_info"], marks=[{"source_index": 1, "mark": "outdated"}]
    )
    payload = content.build_task(temp_db.feedback_detail(feedback_id))

    assert payload["kind"] == "doc_update"
    assert payload["priority"] == "high"
    assert payload["source"] == "hr/leave.md"
    assert payload["heading"] == "年假"
    assert payload["library"] == "hr"
    assert "问题：年假多少天" in payload["description"]


def test_missing_source_becomes_doc_missing(temp_db):
    user = temp_db.create_user("alice", "secret123")
    answer_id = temp_db.create_answer(user["id"], "报销流程", "不知道", "[]")
    feedback_id = temp_db.save_feedback(
        answer_id, user["id"], 1, sentiment="negative",
        reasons=["retrieval_miss"], comment="没找到资料",
    )
    payload = content.build_task(temp_db.feedback_detail(feedback_id))

    assert payload["kind"] == "doc_missing"
    assert payload["priority"] == "medium"
    assert payload["title"] == "报销流程"


def test_create_task_is_idempotent(temp_db):
    user, feedback_id = _feedback(temp_db)

    first = content.create_task_for_feedback(feedback_id, user["id"])
    second = content.create_task_for_feedback(feedback_id, user["id"])

    assert first["created"] is True
    assert second["created"] is False
    assert second["task"]["id"] == first["task"]["id"]


def test_same_source_and_kind_reuses_open_task(temp_db):
    first_user, first_feedback = _feedback(temp_db, username="alice")
    second_user, second_feedback = _feedback(temp_db, username="bob")

    first = content.create_task_for_feedback(first_feedback, first_user["id"])
    second = content.create_task_for_feedback(second_feedback, second_user["id"])

    assert first["created"] is True
    assert second["created"] is False
    assert second["task"]["id"] == first["task"]["id"]
    assert second["task"]["feedback_count"] == 2


def test_update_and_list_tasks(temp_db):
    user, feedback_id = _feedback(temp_db)
    task = content.create_task_for_feedback(feedback_id, user["id"])["task"]

    updated = content_store.update_content_task(
        task["id"], status="resolved", resolution_note="已补文档",
        eval_run_id=7, updated_by=user["id"]
    )
    assert updated["status"] == "resolved"
    assert updated["resolution_note"] == "已补文档"
    assert updated["eval_run_id"] == 7

    page = content_store.list_content_tasks(status="resolved")
    assert page["total"] == 1
    assert page["items"][0]["feedback_count"] == 1
    assert page["items"][0]["eval_run_id"] == 7


def test_positive_feedback_is_not_a_content_task(temp_db):
    user, feedback_id = _feedback(temp_db, reasons=["helpful"], rating=5)

    with pytest.raises(ValueError):
        content.create_task_for_feedback(feedback_id, user["id"])
