"""评测结果入库与查询。

评测脚本可以写主库，也可以写单独的 results.db；管理端只读主库里的
eval_runs / eval_results。这里不依赖评测目录，运行时不会 import evals。
"""
import json
import sqlite3
from contextlib import contextmanager

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    dataset TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    aggregate_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_created ON eval_runs(created_at DESC);
CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    answerable INTEGER NOT NULL DEFAULT 1,
    grounded INTEGER,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(run_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);
"""


@contextmanager
def _connect(path=None):
    if path is None:
        with db.connect() as conn:
            conn.executescript(SCHEMA)
            yield conn
        return
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_run(run_id):
    """校验评测运行存在；0/None 表示清空关联。"""
    if run_id in (None, 0, ""):
        return None
    run_id = int(run_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if not row:
        raise ValueError("评测运行不存在")
    return run_id


def save_payload(payload, path=None):
    """把 run_retrieval_eval 的 payload 写成一次评测运行。"""
    run_key = f"{payload.get('name') or 'retrieval'}-{payload.get('generated_at', '')}"
    now = db.now()
    with _connect(path) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO eval_runs(
                run_key, name, dataset, config_json, aggregate_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_key,
                payload.get("name") or "retrieval",
                payload.get("dataset") or "",
                json.dumps(payload.get("config") or {}, ensure_ascii=False),
                json.dumps(payload.get("aggregate") or {}, ensure_ascii=False),
                now,
            ),
        )
        row = conn.execute(
            "SELECT id FROM eval_runs WHERE run_key = ?", (run_key,)
        ).fetchone()
        run_id = row["id"]
        for case in payload.get("cases") or []:
            grounded = case.get("grounded")
            conn.execute(
                """INSERT OR IGNORE INTO eval_results(
                    run_id, case_id, answerable, grounded, metrics_json, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(case.get("case_id") or ""),
                    1 if case.get("answerable") else 0,
                    None if grounded is None else (1 if grounded else 0),
                    json.dumps(case.get("metrics") or {}, ensure_ascii=False),
                    case.get("error") or "",
                    now,
                ),
            )
        return run_id


def _run_dict(row, detail=False):
    item = dict(row)
    item["config"] = _load(item.pop("config_json", "{}"), {})
    item["aggregate"] = _load(item.pop("aggregate_json", "{}"), {})
    if detail:
        results = []
        for result in item.pop("results", []):
            data = dict(result)
            metrics = _load(data.pop("metrics_json", "{}"), {})
            data["answerable"] = bool(data["answerable"])
            data["grounded"] = (
                None if data["grounded"] is None else bool(data["grounded"])
            )
            data["metrics"] = metrics
            results.append(data)
        item["results"] = results
    return item


def _load(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def list_runs(page=1, page_size=20):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM eval_runs").fetchone()["n"]
        rows = conn.execute(
            """SELECT * FROM eval_runs
               ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
            (page_size, (page - 1) * page_size),
        ).fetchall()
    return {
        "items": [_run_dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def get_run(run_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        results = conn.execute(
            "SELECT * FROM eval_results WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    item = dict(row)
    item["results"] = results
    return _run_dict(item, detail=True)
