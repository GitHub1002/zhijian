"""精选正例：候选生成、审核开关、权限过滤和提示词注入。"""
import json

import pytest

from app import curated_store, db, rag

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


def _candidate(database):
    user = database.create_user("alice", "secret123")
    answer_id = database.create_answer(
        user["id"], "年假多少天", "按工龄计算，最多 15 天。",
        json.dumps(SOURCES, ensure_ascii=False),
    )
    feedback_id = database.save_feedback(
        answer_id, user["id"], 5, sentiment="positive", reasons=["helpful"], comment="很有用"
    )
    return user, answer_id, curated_store.ensure_candidate(answer_id, feedback_id)


def _approved_example(database):
    user, answer_id, candidate = _candidate(database)
    curated_store.update_example(
        candidate["id"],
        status="approved",
        use_as_few_shot=True,
        eval_passed=True,
        eval_run_id=1,
        reviewed_by=user["id"],
    )
    return user, answer_id, candidate


def test_positive_feedback_creates_candidate(temp_db):
    user, answer_id, _ = _candidate(temp_db)

    page = curated_store.list_examples()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["answer_id"] == answer_id
    assert item["question"] == "年假多少天"
    assert item["library"] == "hr"
    assert item["status"] == "candidate"
    assert item["use_as_few_shot"] is False
    assert item["eval_passed"] is False


def test_approved_examples_respect_library_permission(temp_db):
    _approved_example(temp_db)

    assert len(curated_store.approved_examples(3, ["hr"])) == 1
    assert curated_store.approved_examples(3, ["dev"]) == []
    assert curated_store.approved_examples(3, ["common"]) == []


def test_negative_feedback_revokes_candidate(temp_db):
    _, answer_id, candidate = _approved_example(temp_db)

    curated_store.invalidate_candidate(answer_id)
    item = curated_store.get_example(candidate["id"])

    assert item["status"] == "rejected"
    assert item["use_as_few_shot"] is False
    assert item["eval_passed"] is False
    assert curated_store.approved_examples(3, ["hr"]) == []


def test_approved_without_eval_is_not_used(temp_db):
    user, _, candidate = _candidate(temp_db)
    curated_store.update_example(
        candidate["id"],
        status="approved",
        use_as_few_shot=True,
        reviewed_by=user["id"],
    )

    assert curated_store.approved_examples(3, ["hr"]) == []


def test_prompt_includes_examples_only_when_enabled(temp_db, monkeypatch):
    user, _, _ = _approved_example(temp_db)
    state = {
        "question": "年假怎么算",
        "user_id": user["id"],
        "conversation_id": None,
        "context": "[1] 年假按工龄计算",
        "libraries": ["hr"],
    }

    monkeypatch.setattr(rag.config, "CURATED_FEWSHOT_ENABLED", False)
    assert "表达示例" not in rag._prompt_for_state(state)

    monkeypatch.setattr(rag.config, "CURATED_FEWSHOT_ENABLED", True)
    prompt = rag._prompt_for_state(state)
    assert "表达示例" in prompt
    assert "示例回答：按工龄计算，最多 15 天。" in prompt
    assert "不得作为事实来源" in prompt


def test_prompt_filters_examples_by_user_libraries(temp_db, monkeypatch):
    user, _, _ = _approved_example(temp_db)
    state = {
        "question": "年假怎么算",
        "user_id": user["id"],
        "conversation_id": None,
        "context": "[1] 年假按工龄计算",
        "libraries": ["dev"],
    }

    monkeypatch.setattr(rag.config, "CURATED_FEWSHOT_ENABLED", True)
    prompt = rag._prompt_for_state(state)

    assert "表达示例" not in prompt


def test_eval_passed_without_run_is_not_used(temp_db):
    user, _, candidate = _candidate(temp_db)
    curated_store.update_example(
        candidate["id"],
        status="approved",
        use_as_few_shot=True,
        eval_passed=True,
        reviewed_by=user["id"],
    )

    assert curated_store.approved_examples(3, ["hr"]) == []
