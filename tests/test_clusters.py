"""问题聚类：相似问题合并，不同问题分开。"""
import pytest

from app import analytics, db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def test_cluster_rows_groups_similar_questions():
    rows = [
        {"id": 1, "question": "年假有多少天", "reasons": ["wrong_info"]},
        {"id": 2, "question": "年假多少天", "reasons": ["incomplete"]},
        {"id": 3, "question": "报销需要哪些材料", "reasons": ["retrieval_miss"]},
    ]

    clusters = analytics._cluster_rows(rows)
    sizes = sorted(len(cluster["ids"]) for cluster in clusters)

    assert sizes == [1, 2]


def test_negative_feedback_becomes_clusters(temp_db):
    user = temp_db.create_user("alice", "secret123")
    questions = ["年假有多少天", "年假多少天", "报销需要哪些材料"]
    reasons = [["wrong_info"], ["incomplete"], ["retrieval_miss"]]
    for question, reason in zip(questions, reasons):
        answer_id = temp_db.create_answer(user["id"], question, "答案", "[]")
        temp_db.save_feedback(
            answer_id, user["id"], 1, sentiment="negative", reasons=reason, comment="不对"
        )

    items = analytics.clusters(30)

    assert len(items) == 2
    assert items[0]["size"] == 2
    assert items[0]["label"] in {"年假有多少天", "年假多少天"}
    assert items[1]["size"] == 1


def test_clusters_empty_without_negative_feedback(temp_db):
    assert analytics.clusters(30) == []
