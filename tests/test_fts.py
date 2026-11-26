"""FTS：入库增量维护，启动不重建，手动重建可用。"""
import pytest

from app import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _chunk():
    return {
        "id": "c1",
        "source": "hr/leave.md",
        "title": "请假制度",
        "heading": "年假",
        "text": "年假按工龄计算。",
        "library": "hr",
    }


def test_replace_chunks_is_incremental_and_init_does_not_rebuild(temp_db):
    temp_db.replace_search_chunks("hr/leave.md", [_chunk()])

    with temp_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM search_chunks_fts").fetchone()[0] == 1

    temp_db.init_db()

    with temp_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM search_chunks_fts").fetchone()[0] == 1

    results = temp_db.search_bm25("年假", ["hr"])
    assert [row["chunk_id"] for row in results] == ["c1"]


def test_rebuild_fts_is_explicit(temp_db):
    temp_db.replace_search_chunks("hr/leave.md", [_chunk()])
    temp_db.rebuild_fts()

    with temp_db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM search_chunks_fts").fetchone()[0] == 1
