"""v13 迁移：删除从未计算的 eval_runs.passed。"""
import sqlite3

from app import db


def test_migrate_v13_drops_passed_column(tmp_path):
    conn = sqlite3.connect(tmp_path / "v12.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_key TEXT NOT NULL UNIQUE,
            passed INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute("INSERT INTO eval_runs(run_key, passed) VALUES ('run', 0)")

    db._migrate_v13(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(eval_runs)")}
    count = conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0]

    assert "passed" not in columns
    assert count == 1
    conn.close()
