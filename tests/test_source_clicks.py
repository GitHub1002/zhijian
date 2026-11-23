"""引用点击：去重、归属校验和看板指标。"""
import json

import pytest

from app import analytics, db, tracing

SOURCES = [
    {
        "index": 1,
        "source": "hr/leave.md",
        "heading": "年假",
        "anchor": "年假",
        "library": "hr",
    }
]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def test_source_click_is_deduplicated(temp_db):
    user = temp_db.create_user("alice", "secret123")
    answer_id = temp_db.create_answer(
        user["id"], "年假多少天", "5 天", json.dumps(SOURCES, ensure_ascii=False)
    )

    assert temp_db.record_source_click(
        answer_id, user["id"], "hr/leave.md", heading="年假", library="hr"
    ) is True
    assert temp_db.record_source_click(
        answer_id, user["id"], "hr/leave.md", heading="年假", library="hr"
    ) is False
    assert temp_db.record_source_click(
        answer_id, user["id"], "hr/leave.md", heading="病假", library="hr"
    ) is True

    with temp_db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS n FROM source_clicks").fetchone()["n"]
    assert count == 2


def test_overview_includes_citation_click_rate(temp_db):
    user = temp_db.create_user("alice", "secret123")
    answer_id = temp_db.create_answer(
        user["id"], "年假多少天", "5 天", json.dumps(SOURCES, ensure_ascii=False)
    )
    ranked = [
        {
            "chunk_id": "c1",
            "source": "hr/leave.md",
            "heading": "年假",
            "library": "hr",
        }
    ]
    tracing.record(
        answer_id=answer_id,
        user_id=user["id"],
        question="年假多少天",
        ranked=ranked,
        top=ranked,
        grounded=True,
    )
    temp_db.record_source_click(
        answer_id, user["id"], "hr/leave.md", heading="年假", library="hr"
    )

    data = analytics.overview(30)
    assert data["answers_with_sources"] == 1
    assert data["citation_clicks"] == 1
    assert data["citation_clicked_answers"] == 1
    assert data["citation_click_rate"] == 1.0

    libraries = analytics.libraries(30)
    assert libraries[0]["library"] == "hr"
    assert libraries[0]["clicks"] == 1
