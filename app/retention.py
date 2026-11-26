"""保留期清理：只删审计/轨迹/点击和已归档的旧记忆，不动问答和反馈。"""
from datetime import datetime, timedelta, timezone

from . import db


def _cutoff(days):
    return (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()


def cleanup(*, memory_days=90, trace_days=180, click_days=180, audit_days=365,
            dry_run=False):
    specs = (
        ("legacy_assistant_memory", "updated_at", memory_days),
        ("legacy_learning_notes", "created_at", memory_days),
        ("answer_traces", "created_at", trace_days),
        ("source_clicks", "created_at", click_days),
        ("admin_audit_log", "created_at", audit_days),
    )
    counts = {}
    with db.connect() as conn:
        for table, column, days in specs:
            if not db._table_exists(conn, table):
                continue
            cutoff = _cutoff(days)
            count = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {column} < ?", (cutoff,)
            ).fetchone()["n"]
            counts[table] = count
            if count and not dry_run:
                conn.execute(
                    f"DELETE FROM {table} WHERE {column} < ?", (cutoff,)
                )
    return counts
