"""检索轨迹：trace_id、配置快照、候选片段与落库。

回答和拒答都会留下轨迹。轨迹只存分数、排名和来源元数据，不存正文，
避免把整篇文档复制进审计表。
"""
import json
import logging
import uuid

from . import config, db

logger = logging.getLogger(__name__)

PROMPT_VERSION = "2026-11-22.1"
MAX_CANDIDATES = 12
CONFIG_KEYS = (
    "TOP_K",
    "HYBRID_TOP_K",
    "RRF_K",
    "RERANK_TOP_K",
    "RERANK_ENABLED",
    "RERANK_MODEL",
    "MIN_VECTOR_SCORE",
    "RAG_QUERY_REWRITE_LIMIT",
    "EMBED_MODEL",
    "EMBED_DIM",
    "DEEPSEEK_MODEL",
)


def new_trace_id():
    return uuid.uuid4().hex


def config_snapshot(overrides=None):
    snapshot = {}
    for key in CONFIG_KEYS:
        value = getattr(config, key, None)
        if value is None or isinstance(value, (str, int, float, bool)):
            snapshot[key] = value
    snapshot["PROMPT_VERSION"] = PROMPT_VERSION
    snapshot.update(overrides or {})
    return snapshot


def _float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _best(values, better=max):
    present = [value for value in values if value is not None]
    return better(present) if present else None


def _candidate_rows(ranked, selected_ids):
    rows = []
    for rank, item in enumerate(list(ranked or [])[:MAX_CANDIDATES], start=1):
        chunk_id = str(item.get("chunk_id") or "")
        rows.append(
            {
                "rank": rank,
                "chunk_id": chunk_id,
                "source": str(item.get("source") or ""),
                "heading": str(item.get("heading") or ""),
                "library": str(item.get("library") or ""),
                "vector_score": _float(item.get("vector_score")),
                "bm25_score": _float(item.get("bm25_score")),
                "rrf_score": _float(item.get("rrf_score")),
                "rerank_score": _float(item.get("rerank_score")),
                "vector_rank": item.get("vector_rank"),
                "bm25_rank": item.get("bm25_rank"),
                "rrf_rank": item.get("rrf_rank"),
                "selected": 1 if chunk_id in selected_ids else 0,
            }
        )
    return rows


def record(
    *,
    answer_id,
    user_id,
    question,
    queries=None,
    retrieval_query="",
    query_rewrites=0,
    libraries=None,
    grounded=False,
    refusal_reason="",
    ranked=None,
    top=None,
    timings=None,
    error="",
    experiment=None,
    conversation_id=None,
    trace_id=None,
):
    """写入一条 answer_traces 与对应 retrieval_candidates，返回 trace_id。"""
    trace_id = trace_id or new_trace_id()
    ranked = list(ranked or [])
    selected_ids = {str(item.get("chunk_id") or "") for item in (top or [])}
    rows = _candidate_rows(ranked, selected_ids)
    queries = [item for item in (queries or [question]) if item]
    if not queries:
        queries = [question]

    vector_scores = [row["vector_score"] for row in rows]
    bm25_scores = [row["bm25_score"] for row in rows]
    rerank_scores = [row["rerank_score"] for row in rows]

    with db.connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO answer_traces(
                trace_id, answer_id, user_id, conversation_id, question, queries_json,
                retrieval_query, query_rewrites, libraries_json, grounded, refusal_reason,
                vector_hits, bm25_hits, reranked, top_k,
                best_vector_score, best_bm25_score, best_rerank_score,
                config_json, model, prompt_version, experiment_json,
                timings_json, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id,
                answer_id,
                user_id,
                conversation_id,
                question,
                json.dumps(queries, ensure_ascii=False),
                retrieval_query or (queries[-1] if queries else question),
                int(query_rewrites or 0),
                json.dumps(list(libraries or []), ensure_ascii=False),
                1 if grounded else 0,
                refusal_reason or "",
                sum(1 for item in ranked if item.get("vector_score") is not None),
                sum(1 for item in ranked if item.get("bm25_score") is not None),
                len(ranked),
                len(top or []),
                _best(vector_scores, max),
                _best(bm25_scores, min),
                _best(rerank_scores, max),
                json.dumps(config_snapshot(), ensure_ascii=False),
                str(getattr(config, "DEEPSEEK_MODEL", "") or ""),
                PROMPT_VERSION,
                json.dumps(experiment or {}, ensure_ascii=False),
                json.dumps(timings or {}, ensure_ascii=False),
                error or "",
                db.now(),
            ),
        )
        conn.executemany(
            """INSERT INTO retrieval_candidates(
                trace_id, rank, chunk_id, source, heading, library,
                vector_score, bm25_score, rrf_score, rerank_score,
                vector_rank, bm25_rank, rrf_rank, selected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    trace_id,
                    row["rank"],
                    row["chunk_id"],
                    row["source"],
                    row["heading"],
                    row["library"],
                    row["vector_score"],
                    row["bm25_score"],
                    row["rrf_score"],
                    row["rerank_score"],
                    row["vector_rank"],
                    row["bm25_rank"],
                    row["rrf_rank"],
                    row["selected"],
                )
                for row in rows
            ],
        )
    return trace_id


def get_trace(trace_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM answer_traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["candidates"] = [
            dict(item)
            for item in conn.execute(
                "SELECT * FROM retrieval_candidates WHERE trace_id = ? ORDER BY rank",
                (trace_id,),
            ).fetchall()
        ]
        return result


def get_trace_by_answer(answer_id):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT trace_id FROM answer_traces WHERE answer_id = ?", (answer_id,)
        ).fetchone()
    return get_trace(row["trace_id"]) if row else None


def trace_id_for_answer(answer_id):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT trace_id FROM answer_traces WHERE answer_id = ?", (answer_id,)
        ).fetchone()
    return row["trace_id"] if row else None


def record_safely(**kwargs):
    """轨迹写失败不能拖垮一次正常回答；失败时记录日志并返回 None。"""
    try:
        return record(**kwargs)
    except Exception:
        logger.exception("record retrieval trace failed")
        return None
