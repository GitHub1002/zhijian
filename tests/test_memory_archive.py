"""旧记忆表归档：改名、合并、重复执行安全。"""
import pytest

from app import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    return db


def _create_old_tables(conn):
    conn.execute(
        """CREATE TABLE assistant_memory (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            summary TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE learning_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )


def test_old_memory_tables_are_renamed(temp_db):
    user = temp_db.create_user("alice", "secret123")
    with temp_db.connect() as conn:
        _create_old_tables(conn)
        conn.execute(
            "INSERT INTO assistant_memory(user_id, summary, updated_at) VALUES (?, ?, ?)",
            (user["id"], "旧摘要", temp_db.now()),
        )

    temp_db.init_db()

    with temp_db.connect() as conn:
        assert not db._table_exists(conn, "assistant_memory")
        assert not db._table_exists(conn, "learning_notes")
        assert db._table_exists(conn, "legacy_assistant_memory")
        assert db._table_exists(conn, "legacy_learning_notes")
        row = conn.execute(
            "SELECT summary FROM legacy_assistant_memory WHERE user_id = ?", (user["id"],)
        ).fetchone()
    assert row["summary"] == "旧摘要"

    temp_db.init_db()
    with temp_db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM legacy_assistant_memory"
        ).fetchone()["n"] == 1


def test_existing_archive_is_merged(temp_db):
    user = temp_db.create_user("alice", "secret123")
    other = temp_db.create_user("bob", "secret123")
    with temp_db.connect() as conn:
        _create_old_tables(conn)
        conn.execute(
            """CREATE TABLE legacy_assistant_memory (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO assistant_memory(user_id, summary, updated_at) VALUES (?, ?, ?)",
            (user["id"], "旧摘要", temp_db.now()),
        )
        conn.execute(
            "INSERT INTO legacy_assistant_memory(user_id, summary, updated_at) VALUES (?, ?, ?)",
            (other["id"], "归档摘要", temp_db.now()),
        )

    temp_db.init_db()

    with temp_db.connect() as conn:
        assert not db._table_exists(conn, "assistant_memory")
        rows = {
            row["user_id"]: row["summary"]
            for row in conn.execute(
                "SELECT user_id, summary FROM legacy_assistant_memory"
            ).fetchall()
        }
    assert rows[user["id"]] == "旧摘要"
    assert rows[other["id"]] == "归档摘要"


def test_fresh_database_has_no_legacy_tables(temp_db):
    with temp_db.connect() as conn:
        assert not db._table_exists(conn, "assistant_memory")
        assert not db._table_exists(conn, "learning_notes")
        assert not db._table_exists(conn, "legacy_assistant_memory")
