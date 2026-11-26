import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DB_PATH", str(Path(tempfile.gettempdir()) / "rag-trace-collect.db"))

from app import db, rag, tracing  # noqa: E402


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    path = tmp_path / "trace.db"
    monkeypatch.setattr(db, "_DB_PATH", path)
    db.init_db()
    return path


def test_source_dict_keeps_ranking_fields():
    source = rag._source_dict(
        1,
        {
            "chunk_id": "c1",
            "source": "hr/请假制度.md",
            "heading": "请假类型 > 年假",
            "library": "hr",
            "vector_score": 0.82,
            "bm25_score": -12.4,
            "rrf_score": 0.031,
            "rerank_score": 0.91,
        },
    )
    assert source["chunk_id"] == "c1"
    assert source["score"] == 0.91
    assert source["bm25_score"] == -12.4
    assert source["rrf_score"] == 0.031
    assert source["anchor"] == "年假"


def test_refusal_records_trace(isolated_db):
    user = db.create_user("trace_user", "pw")
    result = rag._refusal(
        "没有依据的问题", user["id"], ["hr"], "no_grounded_evidence", ranked=[], top=[]
    )
    trace = tracing.get_trace_by_answer(result["answer_id"])
    assert trace is not None
    assert trace["grounded"] == 0
    assert trace["refusal_reason"] == "no_grounded_evidence"
    assert trace["trace_id"] == result["trace_id"]


def test_feedback_links_to_trace(isolated_db):
    user = db.create_user("feedback_user", "pw")
    result = rag._refusal("问题", user["id"], ["hr"], "no_grounded_evidence")
    feedback_id = db.save_feedback(
        result["answer_id"],
        user["id"], sentiment="negative",
        reasons=["retrieval_miss"],
        comment="没有检索到",
    )
    saved = db.get_feedback(feedback_id, user["id"])
    assert saved["trace_id"] == result["trace_id"]
    assert saved["reasons"] == ["retrieval_miss"]


def test_tracing_record_candidates(isolated_db):
    user = db.create_user("candidate_user", "pw")
    answer_id = db.create_answer(user["id"], "问题", "回答", "[]")
    trace_id = tracing.record(
        answer_id=answer_id,
        user_id=user["id"],
        question="问题",
        ranked=[
            {
                "chunk_id": "c1",
                "source": "a.md",
                "heading": "h",
                "library": "hr",
                "vector_score": 0.8,
                "bm25_score": -10.0,
                "rrf_score": 0.03,
                "rerank_score": 0.9,
            }
        ],
        top=[{"chunk_id": "c1"}],
        grounded=True,
    )
    trace = tracing.get_trace(trace_id)
    assert trace["grounded"] == 1
    assert trace["candidates"][0]["chunk_id"] == "c1"
    assert trace["candidates"][0]["selected"] == 1
