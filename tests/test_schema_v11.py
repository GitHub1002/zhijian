"""v11 迁移：合并旧 reason、删除 reason 列和 legacy 记忆表。"""
import sqlite3


def test_migrate_v11_merges_reason_and_drops_legacy_tables(tmp_path):
    conn = sqlite3.connect(tmp_path / "v10.db")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL DEFAULT ''
        )"""
    )
    conn.execute("INSERT INTO feedback(comment, reason) VALUES ('', '旧原因')")
    conn.execute("INSERT INTO feedback(comment, reason) VALUES ('已有评论', '补充原因')")
    conn.execute(
        "CREATE TABLE legacy_assistant_memory(user_id INTEGER PRIMARY KEY, summary TEXT)"
    )
    conn.execute(
        "CREATE TABLE legacy_learning_notes(id INTEGER PRIMARY KEY, note TEXT)"
    )

    from app import db

    db._migrate_v11(conn)

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback)")}
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    comments = [row["comment"] for row in conn.execute("SELECT comment FROM feedback ORDER BY id")]

    assert "reason" not in columns
    assert "legacy_assistant_memory" not in tables
    assert "legacy_learning_notes" not in tables
    assert comments == ["旧原因", "已有评论\n补充原因"]
    conn.close()
