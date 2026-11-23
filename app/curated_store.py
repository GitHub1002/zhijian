"""精选正例存储。

点赞只生成候选；管理员审核并勾选 use_as_few_shot 后，才可能在全局开关
打开时进入提示词。示例只学习表达方式，不作为事实来源。
"""
import json

from . import db

STATUSES = {"candidate", "approved", "rejected"}


def _load_json(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def _example_dict(row):
    item = dict(row)
    item["sources"] = _load_json(item.pop("sources_json", "[]"), [])
    item["use_as_few_shot"] = bool(item.get("use_as_few_shot"))
    return item


def _fetch(conn, example_id):
    row = conn.execute(
        "SELECT * FROM curated_examples WHERE id = ?", (example_id,)
    ).fetchone()
    return _example_dict(row) if row else None


def ensure_candidate(answer_id, feedback_id):
    """点赞后生成候选；已被否决的回答再次点赞时恢复为候选。"""
    with db.connect() as conn:
        answer = conn.execute(
            "SELECT id, question, answer, sources_json FROM answers WHERE id = ?",
            (answer_id,),
        ).fetchone()
        if not answer:
            return None
        existing = conn.execute(
            "SELECT * FROM curated_examples WHERE answer_id = ?", (answer_id,)
        ).fetchone()
        now = db.now()
        if existing:
            if existing["status"] == "rejected":
                conn.execute(
                    """UPDATE curated_examples
                       SET status = 'candidate', feedback_id = ?, updated_at = ?
                       WHERE id = ?""",
                    (feedback_id, now, existing["id"]),
                )
            return _fetch(conn, existing["id"])

        sources = _load_json(answer["sources_json"], [])
        library = ""
        for item in sources:
            if isinstance(item, dict) and item.get("library"):
                library = item["library"]
                break
        cur = conn.execute(
            """INSERT INTO curated_examples(
                answer_id, feedback_id, question, answer, sources_json, library,
                status, use_as_few_shot, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'candidate', 0, ?, ?)""",
            (
                answer["id"],
                feedback_id,
                answer["question"],
                answer["answer"],
                answer["sources_json"] or "[]",
                library,
                now,
                now,
            ),
        )
        return _fetch(conn, cur.lastrowid)


def invalidate_candidate(answer_id):
    """用户把点赞改成点踩时撤销候选，避免继续被审核或使用。"""
    with db.connect() as conn:
        conn.execute(
            """UPDATE curated_examples
               SET status = 'rejected', use_as_few_shot = 0, updated_at = ?
               WHERE answer_id = ?""",
            (db.now(), answer_id),
        )


def list_examples(page=1, page_size=20, *, status=None, library=None):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    where = []
    params = []
    if status:
        where.append("c.status = ?")
        params.append(status)
    if library:
        where.append("c.library = ?")
        params.append(library)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"""FROM curated_examples c
               LEFT JOIN users u ON u.id = c.reviewed_by
               {clause}"""
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT c.*, u.username AS reviewer_name
                {base}
                ORDER BY c.updated_at DESC, c.id DESC
                LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [_example_dict(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def get_example(example_id):
    with db.connect() as conn:
        return _fetch(conn, example_id)


def update_example(example_id, *, status=None, use_as_few_shot=None, reviewed_by=None):
    updates = {}
    if status is not None:
        updates["status"] = status
        updates["reviewed_by"] = reviewed_by
        updates["reviewed_at"] = db.now()
    if use_as_few_shot is not None:
        updates["use_as_few_shot"] = 1 if use_as_few_shot else 0
    if not updates:
        return get_example(example_id)
    updates["updated_at"] = db.now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    with db.connect() as conn:
        if not conn.execute(
            "SELECT 1 FROM curated_examples WHERE id = ?", (example_id,)
        ).fetchone():
            return None
        conn.execute(
            f"UPDATE curated_examples SET {assignments} WHERE id = ?",
            [*updates.values(), example_id],
        )
        return _fetch(conn, example_id)


def approved_examples(limit=3, libraries=None):
    """只返回已审核、允许 few-shot、且用户有权阅读的示例。"""
    limit = max(1, min(10, int(limit or 3)))
    allowed = [item for item in (libraries or []) if item]
    allowed = sorted({"", "common", *allowed})
    placeholders = ", ".join("?" for _ in allowed)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT question, answer, library FROM curated_examples
                WHERE status = 'approved' AND use_as_few_shot = 1
                  AND library IN ({placeholders})
                ORDER BY updated_at DESC, id DESC
                LIMIT ?""",
            [*allowed, limit],
        ).fetchall()
    return [dict(row) for row in rows]
