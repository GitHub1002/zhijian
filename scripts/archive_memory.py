"""把旧的 assistant_memory / learning_notes 导出为 JSON，便于下线前留档。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from app import db


def main():
    out_dir = Path("data/archive")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {}
    with db.connect() as conn:
        for table in (
            "assistant_memory",
            "learning_notes",
            "legacy_assistant_memory",
            "legacy_learning_notes",
        ):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            payload[table] = (
                [dict(item) for item in conn.execute(f"SELECT * FROM {table}").fetchall()]
                if exists
                else []
            )
    path = out_dir / f"memory_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {path}")


if __name__ == "__main__":
    main()
