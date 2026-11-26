"""启动初始化：import 不建库，FastAPI lifespan 才建表。"""
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app import db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent


def test_import_does_not_create_database(tmp_path):
    target = tmp_path / "import-only.db"
    env = os.environ.copy()
    env["DB_PATH"] = str(target)

    result = subprocess.run(
        [sys.executable, "-c", "from app import db"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not target.exists()


def test_lifespan_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "app.db")

    with TestClient(app) as client:
        assert client.get("/api/auth/me").status_code == 401

    with db.connect() as conn:
        assert db._table_exists(conn, "users")
