"""v12 迁移：任务首反馈并入 join 表，删除冗余列。"""
import sqlite3

from app import db


def test_migrate_v12_moves_feedback_id_to_join_table(tmp_path):
    conn = sqlite3.connect(tmp_path / "v11.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE content_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feedback_id INTEGER,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE content_task_feedback (
            task_id INTEGER NOT NULL,
            feedback_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (task_id, feedback_id)
        )"""
    )
    conn.execute(
        "INSERT INTO content_tasks(feedback_id, created_at) VALUES (7, '2026-11-26')"
    )

    db._migrate_v12(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(content_tasks)")}
    linked = conn.execute(
        "SELECT task_id, feedback_id FROM content_task_feedback"
    ).fetchall()

    assert "feedback_id" not in columns
    assert [tuple(row) for row in linked] == [(1, 7)]
    conn.close()
