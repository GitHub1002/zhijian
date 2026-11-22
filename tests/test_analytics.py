"""管理端看板聚合与导出筛选。"""
import pytest

from app import analytics, db, tracing


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _seed(database):
    user = database.create_user("alice", "secret123")
    answer_id = database.create_answer(user["id"], "年假多少天", "5 天", "[]")
    ranked = [
        {
            "chunk_id": "c1",
            "source": "hr/leave.md",
            "heading": "年假",
            "library": "hr",
            "vector_score": 0.8,
            "bm25_score": -1.2,
            "rrf_score": 0.03,
            "rerank_score": 4.2,
        }
    ]
    tracing.record(
        answer_id=answer_id,
        user_id=user["id"],
        question="年假多少天",
        libraries=["hr"],
        ranked=ranked,
        top=ranked,
        grounded=True,
    )
    database.save_feedback(
        answer_id,
        user["id"],
        1,
        sentiment="negative",
        reasons=["wrong_info"],
        comment="答案不对",
    )
    return user, answer_id


def test_overview_counts(temp_db):
    _seed(temp_db)
    data = analytics.overview(30)

    assert data["answers"] == 1
    assert data["traces"] == 1
    assert data["grounded"] == 1
    assert data["refusals"] == 0
    assert data["feedback"] == 1
    assert data["negative"] == 1
    assert data["grounded_rate"] == 1.0
    assert data["negative_rate"] == 1.0
    assert data["feedback_coverage"] == 1.0


def test_libraries_reasons_and_categories(temp_db):
    _seed(temp_db)

    assert analytics.libraries(30) == [
        {"library": "hr", "answers": 1, "selected_chunks": 1, "negative": 1}
    ]
    assert analytics.reasons(30) == [{"reason": "wrong_info", "count": 1}]
    assert analytics.categories(30) == [{"category": "unknown", "count": 1}]


def test_timeseries_fills_every_day(temp_db):
    _seed(temp_db)
    items = analytics.timeseries(7)

    assert len(items) == 7
    assert items[-1]["answers"] == 1
    assert items[-1]["feedback"] == 1
    assert sum(item["answers"] for item in items) == 1


def test_days_are_clamped(temp_db):
    assert analytics._days(9999) == analytics.MAX_DAYS
    assert analytics._days("bad") == analytics.DEFAULT_DAYS


def test_export_feedback_reuses_filters(temp_db):
    _seed(temp_db)

    rows = temp_db.export_feedback(sentiment="negative")
    assert len(rows) == 1
    assert rows[0]["reasons"] == "wrong_info"
    assert rows[0]["libraries"] == "hr"
    assert temp_db.export_feedback(sentiment="positive") == []
