"""评测结果入库：保存、查询、幂等和独立结果库。"""
import sqlite3

import pytest

from app import db, eval_store


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _payload(name="seed_v2"):
    return {
        "name": name,
        "dataset": "/tmp/seed_v2.jsonl",
        "generated_at": "2026-11-26T00:00:00+00:00",
        "config": {"requested": {}, "applied": {}},
        "aggregate": {"hit@5": 1.0, "false_answer_rate": 0.0},
        "cases": [
            {
                "case_id": "c1",
                "answerable": True,
                "grounded": True,
                "metrics": {"hit@5": 1.0},
                "error": "",
            },
            {
                "case_id": "c2",
                "answerable": False,
                "grounded": False,
                "metrics": {},
                "error": "",
            },
        ],
    }


def test_save_and_list(temp_db):
    run_id = eval_store.save_payload(_payload())

    page = eval_store.list_runs()
    assert page["total"] == 1
    assert page["items"][0]["aggregate"]["hit@5"] == 1.0

    detail = eval_store.get_run(run_id)
    assert len(detail["results"]) == 2
    assert detail["results"][0]["metrics"]["hit@5"] == 1.0
    assert detail["results"][1]["answerable"] is False
    assert detail["results"][1]["grounded"] is False


def test_save_is_idempotent(temp_db):
    first = eval_store.save_payload(_payload())
    second = eval_store.save_payload(_payload())

    assert first == second
    assert eval_store.list_runs()["total"] == 1


def test_save_to_custom_results_db(temp_db, tmp_path):
    path = tmp_path / "results.db"
    eval_store.save_payload(_payload("custom"), path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM eval_results").fetchone()[0] == 2
    finally:
        conn.close()
