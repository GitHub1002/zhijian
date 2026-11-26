"""反馈存储：反馈、来源标记、分诊、列表、导出和详情。

从 db.py 拆出，保持 db.save_feedback 等对外 API 不变。
"""
from . import db


def _connect():
    return db._connect()


def _now():
    return db._now()


def _load_json(value, fallback):
    return db._load_json(value, fallback)


def _dump_json(value):
    return db._dump_json(value)


def _feedback_dict(conn, row):
    item = dict(row)
    item["reasons"] = _load_json(item.pop("reasons_json", "[]"), [])
    item["source_marks"] = [
        dict(mark)
        for mark in conn.execute(
            """SELECT source_index, source, heading, mark
               FROM feedback_source_marks WHERE feedback_id = ? ORDER BY source_index""",
            (row["id"],),
        ).fetchall()
    ]
    return item


def _insert_source_marks(conn, feedback_id, sources_json, marks, now):
    sources = _load_json(sources_json, [])
    for mark in marks or []:
        index = int(mark.get("source_index") or 0)
        if index < 1 or index > len(sources):
            continue
        source = sources[index - 1] or {}
        conn.execute(
            """INSERT OR IGNORE INTO feedback_source_marks(
                feedback_id, source_index, source, heading, mark, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                feedback_id,
                index,
                source.get("source", ""),
                source.get("heading", ""),
                mark.get("mark", ""),
                now,
            ),
        )


def _trace_id_for_answer(conn, answer_id):
    row = conn.execute(
        "SELECT trace_id FROM answer_traces WHERE answer_id = ?", (answer_id,)
    ).fetchone()
    return row["trace_id"] if row else None


def save_feedback(answer_id, user_id, *, sentiment, reasons=None,
                  comment="", corrected_answer="", source_marks=None):
    """写入情感、原因和来源标记；rating 列由 sentiment 推导，兼容历史数据。"""
    if sentiment not in {"positive", "negative"}:
        raise ValueError("sentiment 只能是 positive 或 negative")
    now = _now()
    rating = 5 if sentiment == "positive" else 1
    with _connect() as conn:
        answer = conn.execute(
            "SELECT sources_json FROM answers WHERE id = ? AND user_id = ?",
            (answer_id, user_id),
        ).fetchone()
        if not answer:
            return None
        trace_id = _trace_id_for_answer(conn, answer_id)
        cur = conn.execute(
            """INSERT INTO feedback(
                answer_id, user_id, rating, sentiment, reasons_json, comment,
                corrected_answer, trace_id, status, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (
                answer_id,
                user_id,
                rating,
                sentiment,
                _dump_json(list(reasons or [])),
                comment,
                corrected_answer,
                trace_id,
                now,
                now,
            ),
        )
        feedback_id = cur.lastrowid
        _insert_source_marks(conn, feedback_id, answer["sources_json"], source_marks, now)
        return feedback_id


def get_feedback(feedback_id, user_id=None):
    with _connect() as conn:
        sql = "SELECT * FROM feedback WHERE id = ?"
        params = [feedback_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        row = conn.execute(sql, params).fetchone()
        return _feedback_dict(conn, row) if row else None


def get_feedback_by_answer(answer_id, user_id=None):
    with _connect() as conn:
        sql = "SELECT * FROM feedback WHERE answer_id = ?"
        params = [answer_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        row = conn.execute(sql, params).fetchone()
        return _feedback_dict(conn, row) if row else None


def update_feedback(feedback_id, user_id, *, sentiment=None, reasons=None, comment=None,
                    corrected_answer=None, source_marks=None):
    """修改本人反馈；每次修改前把旧值写入 feedback_revisions。"""
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM feedback WHERE id = ? AND user_id = ?", (feedback_id, user_id)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """INSERT INTO feedback_revisions(
                feedback_id, actor_id, actor_type, snapshot_json, created_at
            ) VALUES (?, ?, 'user', ?, ?)""",
            (feedback_id, user_id, _dump_json(dict(row)), now),
        )
        updates = {"updated_at": now}
        if sentiment is not None:
            updates["sentiment"] = sentiment
            updates["rating"] = 5 if sentiment == "positive" else 1
        if reasons is not None:
            updates["reasons_json"] = _dump_json(list(reasons))
        if comment is not None:
            updates["comment"] = comment
        if corrected_answer is not None:
            updates["corrected_answer"] = corrected_answer
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE feedback SET {assignments} WHERE id = ?",
            [*updates.values(), feedback_id],
        )
        if source_marks is not None:
            conn.execute(
                "DELETE FROM feedback_source_marks WHERE feedback_id = ?", (feedback_id,)
            )
            answer = conn.execute(
                "SELECT sources_json FROM answers WHERE id = ?", (row["answer_id"],)
            ).fetchone()
            if answer:
                _insert_source_marks(conn, feedback_id, answer["sources_json"], source_marks, now)
        updated = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        return _feedback_dict(conn, updated)


def set_feedback_triage(feedback_id, category, confidence=0.0, note=""):
    with _connect() as conn:
        conn.execute(
            """UPDATE feedback SET triage_category = ?, triage_confidence = ?,
               triage_note = ?, updated_at = ? WHERE id = ?""",
            (category, float(confidence or 0), note or "", _now(), feedback_id),
        )


def _feedback_filters(*, sentiment=None, category=None, status=None, library=None,
                      grounded=None, date_from=None, date_to=None, q=None):
    """列表和 CSV 导出共用同一套筛选条件，避免两边口径漂移。"""
    where = []
    params = []
    if sentiment:
        where.append("f.sentiment = ?")
        params.append(sentiment)
    if category:
        where.append("f.triage_category = ?")
        params.append(category)
    if status:
        where.append("f.status = ?")
        params.append(status)
    if library:
        where.append("t.libraries_json LIKE ?")
        params.append(f'%"{library}"%')
    if grounded is not None:
        where.append("t.grounded = ?")
        params.append(1 if grounded else 0)
    if date_from:
        where.append("f.created_at >= ?")
        params.append(date_from)
    if date_to:
        where.append("f.created_at <= ?")
        params.append(date_to)
    if q:
        where.append("(a.question LIKE ? OR f.comment LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def list_feedback(page=1, page_size=20, *, sentiment=None, category=None, status=None,
                  library=None, grounded=None, date_from=None, date_to=None, q=None):
    page = max(1, int(page or 1))
    page_size = min(100, max(1, int(page_size or 20)))
    clause, params = _feedback_filters(
        sentiment=sentiment, category=category, status=status, library=library,
        grounded=grounded, date_from=date_from, date_to=date_to, q=q,
    )
    base = f"""FROM feedback f
               LEFT JOIN answers a ON a.id = f.answer_id
               LEFT JOIN answer_traces t ON t.answer_id = f.answer_id
               LEFT JOIN users u ON u.id = f.user_id
               {clause}"""
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT f.id, f.answer_id, f.user_id, u.username, f.rating, f.sentiment,
                       f.reasons_json, f.comment, f.status, f.triage_category,
                       f.triage_confidence, f.triage_note, f.created_at, f.updated_at,
                       a.question, substr(a.answer, 1, 160) AS answer_snippet,
                       t.grounded, t.refusal_reason, t.best_rerank_score, t.top_k,
                       t.libraries_json
                {base}
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["reasons"] = _load_json(item.pop("reasons_json", "[]"), [])
        item["libraries"] = _load_json(item.pop("libraries_json", "[]"), [])
        items.append(item)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def export_feedback(limit=10000, **filters):
    """导出反馈明细，默认最多 10000 行；筛选口径与 list_feedback 一致。"""
    clause, params = _feedback_filters(**filters)
    limit = max(1, min(10000, int(limit or 10000)))
    base = f"""FROM feedback f
               LEFT JOIN answers a ON a.id = f.answer_id
               LEFT JOIN answer_traces t ON t.answer_id = f.answer_id
               LEFT JOIN users u ON u.id = f.user_id
               {clause}"""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT f.id, f.created_at, f.user_id, u.username, a.question,
                       substr(a.answer, 1, 1000) AS answer,
                       f.sentiment, f.rating, f.reasons_json, f.comment,
                       f.corrected_answer, f.status, f.triage_category, f.triage_note,
                       t.grounded, t.refusal_reason, t.best_rerank_score, t.libraries_json
                {base}
                ORDER BY f.created_at DESC, f.id DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["reasons"] = "、".join(_load_json(item.pop("reasons_json", "[]"), []))
        item["libraries"] = "、".join(_load_json(item.pop("libraries_json", "[]"), []))
        items.append(item)
    return items


def feedback_detail(feedback_id):
    with _connect() as conn:
        row = conn.execute(
            """SELECT f.*, a.question, a.answer, a.sources_json, u.username
               FROM feedback f
               LEFT JOIN answers a ON a.id = f.answer_id
               LEFT JOIN users u ON u.id = f.user_id
               WHERE f.id = ?""",
            (feedback_id,),
        ).fetchone()
        if not row:
            return None
        item = _feedback_dict(conn, row)
        item["question"] = row["question"]
        item["answer"] = row["answer"]
        item["sources"] = _load_json(row["sources_json"], [])
        item["username"] = row["username"]
        trace = conn.execute(
            "SELECT * FROM answer_traces WHERE answer_id = ?", (row["answer_id"],)
        ).fetchone()
        item["trace"] = None
        if trace:
            trace_item = dict(trace)
            trace_item["candidates"] = [
                dict(candidate)
                for candidate in conn.execute(
                    "SELECT * FROM retrieval_candidates WHERE trace_id = ? ORDER BY rank",
                    (trace["trace_id"],),
                ).fetchall()
            ]
            item["trace"] = trace_item
        revisions = []
        for revision in conn.execute(
            """SELECT r.id, r.actor_id, r.actor_type, r.snapshot_json,
                      r.created_at, u.username AS actor_name
               FROM feedback_revisions r
               LEFT JOIN users u ON u.id = r.actor_id
               WHERE r.feedback_id = ? ORDER BY r.id""",
            (feedback_id,),
        ).fetchall():
            snapshot = _load_json(revision["snapshot_json"], {})
            snapshot["reasons"] = _load_json(snapshot.get("reasons_json", "[]"), [])
            revisions.append({**dict(revision), "snapshot": snapshot})
        item["revisions"] = revisions
        item["triage_events"] = [
            dict(event)
            for event in conn.execute(
                """SELECT e.id, e.actor_id, e.from_status, e.to_status,
                          e.category, e.note, e.created_at, u.username AS actor_name
                   FROM feedback_triage_events e
                   LEFT JOIN users u ON u.id = e.actor_id
                   WHERE e.feedback_id = ? ORDER BY e.id""",
                (feedback_id,),
            ).fetchall()
        ]
        return item


def triage_feedback(feedback_id, actor_id, status, category, note=""):
    with _connect() as conn:
        row = conn.execute("SELECT status FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        if not row:
            return None
        now = _now()
        conn.execute(
            """INSERT INTO feedback_triage_events(
                feedback_id, actor_id, from_status, to_status, category, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (feedback_id, actor_id, row["status"], status, category, note or "", now),
        )
        conn.execute(
            """UPDATE feedback SET status = ?, triage_category = ?, triage_note = ?,
               triaged_by = ?, triaged_at = ?, updated_at = ? WHERE id = ?""",
            (status, category, note or "", actor_id, now, now, feedback_id),
        )
        updated = conn.execute("SELECT * FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
        return _feedback_dict(conn, updated)



def record_source_click(answer_id, user_id, source, heading="", anchor="",
                        library="", source_index=0):
    """同一用户对同一来源只计一次点击，避免刷新或连点刷高引用点击率。"""
    with _connect() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO source_clicks(
                answer_id, user_id, source, heading, anchor, library,
                source_index, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                answer_id,
                user_id,
                source or "",
                heading or "",
                anchor or "",
                library or "",
                int(source_index or 0),
                _now(),
            ),
        )
        return cur.rowcount > 0
