"""质量看板聚合查询压测。

在临时库里造 answers / traces / feedback / clicks 数据，测量 overview、
libraries、reasons、categories、clusters 的耗时。默认不写主库。

示例：
  python scripts/bench_analytics.py --rows 10000
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import analytics, db  # noqa: E402


def _seed(rows, db_path):
    db._DB_PATH = db_path
    db.init_db()
    user = db.create_user("bench", "secret123")
    if not user:
        with db.connect() as conn:
            user = dict(conn.execute(
                "SELECT id, username FROM users WHERE username = 'bench'"
            ).fetchone())
    user_id = user["id"]
    now = db.now()
    sources = json.dumps(
        [{"index": 1, "source": "bench/doc.md", "heading": "示例", "library": "hr"}],
        ensure_ascii=False,
    )
    with db.connect() as conn:
        conn.executemany(
            """INSERT INTO answers(user_id, question, answer, sources_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (user_id, f"问题 {index}", f"回答 {index}", sources, now)
                for index in range(rows)
            ],
        )
        answer_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM answers WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()
        ]
        conn.executemany(
            """INSERT INTO answer_traces(
                trace_id, answer_id, user_id, question, queries_json,
                retrieval_query, libraries_json, grounded, refusal_reason,
                vector_hits, bm25_hits, reranked, top_k,
                best_vector_score, best_bm25_score, best_rerank_score,
                config_json, model, prompt_version, experiment_json,
                timings_json, error, created_at
            ) VALUES (?, ?, ?, ?, '[]', ?, '["hr"]', ?, '', 1, 1, 1, 1,
                      0.8, -1.0, 4.0, '{}', '', '', '{}', ?, '', ?)""",
            [
                (
                    f"t{answer_id}",
                    answer_id,
                    user_id,
                    f"问题 {answer_id}",
                    f"问题 {answer_id}",
                    1 if answer_id % 10 else 0,
                    json.dumps({"prepare_ms": 100 + answer_id % 300}),
                    now,
                )
                for answer_id in answer_ids
            ],
        )
        conn.executemany(
            """INSERT INTO retrieval_candidates(
                trace_id, rank, chunk_id, source, heading, library,
                vector_score, bm25_score, rrf_score, rerank_score,
                vector_rank, bm25_rank, rrf_rank, selected
            ) VALUES (?, 1, ?, 'bench/doc.md', '示例', 'hr',
                      0.8, -1.0, 0.03, 4.0, 1, 1, 1, 1)""",
            [(f"t{answer_id}", f"c{answer_id}") for answer_id in answer_ids],
        )
        feedback_rows = []
        for index, answer_id in enumerate(answer_ids[: max(1, rows // 2)]):
            feedback_rows.append(
                (
                    answer_id,
                    user_id,
                    1,
                    "wrong_info",
                    "negative",
                    '["wrong_info"]',
                    "示例反馈",
                    f"t{answer_id}",
                    now,
                    now,
                )
            )
        conn.executemany(
            """INSERT INTO feedback(
                answer_id, user_id, rating, reason, sentiment, reasons_json,
                comment, trace_id, status, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            feedback_rows,
        )
        conn.executemany(
            """INSERT OR IGNORE INTO source_clicks(
                answer_id, user_id, source, heading, anchor, library,
                source_index, created_at
            ) VALUES (?, ?, 'bench/doc.md', '示例', '示例', 'hr', 1, ?)""",
            [(answer_id, user_id, now) for answer_id in answer_ids],
        )
    return user_id


def _time(label, func):
    started = time.perf_counter()
    result = func()
    elapsed = int((time.perf_counter() - started) * 1000)
    print(f"  {label:12} {elapsed:5} ms")
    return elapsed, result


def main():
    parser = argparse.ArgumentParser(description="质量看板聚合压测")
    parser.add_argument("--rows", type=int, default=10000)
    parser.add_argument("--db-path", default=str(ROOT / "data" / "eval" / "bench_analytics.db"))
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    path = Path(args.db_path)
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    started = time.perf_counter()
    _seed(max(1, args.rows), path)
    print(f"seeded {args.rows} answers in {time.perf_counter() - started:.1f}s")
    print("ANALYTICS BENCH")
    print("=" * 24)
    results = {}
    for label, func in (
        ("overview", lambda: analytics.overview(30)),
        ("timeseries", lambda: analytics.timeseries(30)),
        ("libraries", lambda: analytics.libraries(30)),
        ("reasons", lambda: analytics.reasons(30)),
        ("categories", lambda: analytics.categories(30)),
        ("clusters", lambda: analytics.clusters(30)),
    ):
        results[label] = _time(label, func)[0]
    print(f"\n  max: {max(results.values())} ms")
    if not args.keep:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
