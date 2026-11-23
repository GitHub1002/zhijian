"""管理端操作审计。

只记录动作、目标和少量状态字段，不记录问题、回答、评论或导出内容。
"""
import json

from . import db


def log(actor_id, action, target_type, target_id=None, detail=None):
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO admin_audit_log(
                actor_id, action, target_type, target_id, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                actor_id,
                action,
                target_type or "",
                "" if target_id is None else str(target_id),
                json.dumps(detail or {}, ensure_ascii=False),
                db.now(),
            ),
        )


def list_events(page=1, page_size=20, *, action=None, target_type=None,
                actor_id=None, date_from=None, date_to=None):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    where = []
    params = []
    if action:
        where.append("l.action = ?")
        params.append(action)
    if target_type:
        where.append("l.target_type = ?")
        params.append(target_type)
    if actor_id is not None:
        where.append("l.actor_id = ?")
        params.append(int(actor_id))
    if date_from:
        where.append("l.created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("l.created_at <= ?")
        params.append(date_to)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"""FROM admin_audit_log l
               LEFT JOIN users u ON u.id = l.actor_id
               {clause}"""
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT l.*, u.username AS actor_name
                {base}
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json", "{}") or "{}")
        except (TypeError, ValueError):
            item["detail"] = {}
        items.append(item)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }
