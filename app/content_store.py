"""内容任务的 SQLite 存储。

从 db.py 拆出来，避免继续把新表逻辑堆进已经很大的持久化层。
只通过 db.connect()/db.now() 复用连接与时间格式。
"""
from . import db, eval_store


def _connect():
    return db.connect()


def _now():
    return db.now()


def _content_task_dict(conn, row):
    item = dict(row)
    item["feedback_ids"] = [
        feedback["feedback_id"]
        for feedback in conn.execute(
            """SELECT feedback_id FROM content_task_feedback
               WHERE task_id = ? ORDER BY created_at, feedback_id""",
            (row["id"],),
        ).fetchall()
    ]
    item["feedback_count"] = len(item["feedback_ids"])
    return item


def _content_task_row(conn, task_id):
    return conn.execute("SELECT * FROM content_tasks WHERE id = ?", (task_id,)).fetchone()


def get_content_task(task_id):
    with _connect() as conn:
        row = _content_task_row(conn, task_id)
        return _content_task_dict(conn, row) if row else None


def list_content_tasks(page=1, page_size=20, *, status=None, priority=None,
                       kind=None, library=None, q=None):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    where = []
    params = []
    if status:
        where.append("t.status = ?")
        params.append(status)
    if priority:
        where.append("t.priority = ?")
        params.append(priority)
    if kind:
        where.append("t.kind = ?")
        params.append(kind)
    if library:
        where.append("t.library = ?")
        params.append(library)
    if q:
        where.append("(t.title LIKE ? OR t.description LIKE ? OR t.source LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"""FROM content_tasks t
               LEFT JOIN users u ON u.id = t.owner_id
               {clause}"""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT t.*, u.username AS owner_name,
                       (SELECT COUNT(*) FROM content_task_feedback cf
                        WHERE cf.task_id = t.id) AS feedback_count
                {base}
                ORDER BY t.created_at DESC, t.id DESC
                LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def create_content_task(*, title, description="", source="", heading="", library="",
                        kind="doc_fix", priority="medium", created_by=None,
                        owner_id=None, feedback_id=None, eval_run_id=None):
    eval_run_id = eval_store.ensure_run(eval_run_id)
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO content_tasks(
                source, heading, library, title, description, kind, priority, status,
                owner_id, created_by, updated_by, eval_run_id,
                resolution_note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, '', ?, ?)""",
            (
                source or "", heading or "", library or "", title, description or "",
                kind or "doc_fix", priority or "medium", owner_id, created_by,
                created_by, eval_run_id, now, now,
            ),
        )
        task_id = cur.lastrowid
        if feedback_id:
            conn.execute(
                """INSERT OR IGNORE INTO content_task_feedback(
                    task_id, feedback_id, created_at
                ) VALUES (?, ?, ?)""",
                (task_id, feedback_id, now),
            )
        row = _content_task_row(conn, task_id)
        return _content_task_dict(conn, row)


def update_content_task(task_id, *, status=None, priority=None, kind=None,
                        owner_id=None, resolution_note=None, eval_run_id=None,
                        updated_by=None):
    updates = {}
    if status is not None:
        updates["status"] = status
    if priority is not None:
        updates["priority"] = priority
    if kind is not None:
        updates["kind"] = kind
    if owner_id is not None:
        updates["owner_id"] = owner_id
    if resolution_note is not None:
        updates["resolution_note"] = resolution_note
    if eval_run_id is not None:
        updates["eval_run_id"] = eval_store.ensure_run(eval_run_id)
    if not updates:
        return get_content_task(task_id)
    updates["updated_at"] = _now()
    if updated_by is not None:
        updates["updated_by"] = updated_by
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with _connect() as conn:
        if not _content_task_row(conn, task_id):
            return None
        conn.execute(
            f"UPDATE content_tasks SET {assignments} WHERE id = ?",
            [*updates.values(), task_id],
        )
        row = _content_task_row(conn, task_id)
        return _content_task_dict(conn, row)


def find_linked_content_task(feedback_id):
    with _connect() as conn:
        row = conn.execute(
            """SELECT t.* FROM content_tasks t
               JOIN content_task_feedback cf ON cf.task_id = t.id
               WHERE cf.feedback_id = ? LIMIT 1""",
            (feedback_id,),
        ).fetchone()
        return _content_task_dict(conn, row) if row else None


def find_open_content_task(source, heading, kind):
    if not source:
        return None
    with _connect() as conn:
        row = conn.execute(
            """SELECT * FROM content_tasks
               WHERE source = ? AND heading = ? AND kind = ?
                 AND status IN ('open', 'in_progress')
               ORDER BY id LIMIT 1""",
            (source, heading or "", kind or "doc_fix"),
        ).fetchone()
        return _content_task_dict(conn, row) if row else None


def link_content_task_feedback(task_id, feedback_id):
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO content_task_feedback(
                task_id, feedback_id, created_at
            ) VALUES (?, ?, ?)""",
            (task_id, feedback_id, _now()),
        )
