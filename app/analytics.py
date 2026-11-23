"""管理端质量看板聚合查询。

只读 SQLite，不调用模型。时间窗口统一按 UTC 计算；所有列表都带明确上限，
避免在万级 answers 上把整表读进内存。
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import db

DEFAULT_DAYS = 30
MAX_DAYS = 365
CLUSTER_THRESHOLD = 0.3


def _days(value):
    try:
        return max(1, min(MAX_DAYS, int(value or DEFAULT_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def _since(days):
    return (datetime.now(timezone.utc) - timedelta(days=_days(days))).isoformat()


def _int(value):
    return int(value or 0)


def _rate(part, total):
    return round(part / total, 4) if total else 0.0


def overview(days=DEFAULT_DAYS):
    since = _since(days)
    with db.connect() as conn:
        answers = _int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM answers WHERE created_at >= ?", (since,)
            ).fetchone()["n"]
        )
        traces = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN grounded = 1 THEN 1 ELSE 0 END) AS grounded,
                      SUM(CASE WHEN grounded = 0 THEN 1 ELSE 0 END) AS refused,
                      SUM(CASE WHEN refusal_reason = 'no_approved_permission'
                               THEN 1 ELSE 0 END) AS no_permission
               FROM answer_traces WHERE created_at >= ?""",
            (since,),
        ).fetchone()
        feedback = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN sentiment = 'positive' THEN 1 ELSE 0 END) AS positive,
                      SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative,
                      COUNT(DISTINCT answer_id) AS covered
               FROM feedback WHERE created_at >= ?""",
            (since,),
        ).fetchone()
        answers_with_sources = _int(
            conn.execute(
                """SELECT COUNT(*) AS n FROM answers
                   WHERE created_at >= ? AND sources_json NOT IN ('[]', '')""",
                (since,),
            ).fetchone()["n"]
        )
        clicks = conn.execute(
            """SELECT COUNT(*) AS clicks, COUNT(DISTINCT answer_id) AS clicked
               FROM source_clicks WHERE created_at >= ?""",
            (since,),
        ).fetchone()

    trace_total = _int(traces["total"])
    feedback_total = _int(feedback["total"])
    return {
        "days": _days(days),
        "answers": answers,
        "traces": trace_total,
        "grounded": _int(traces["grounded"]),
        "refusals": _int(traces["refused"]),
        "no_permission_refusals": _int(traces["no_permission"]),
        "grounded_rate": _rate(_int(traces["grounded"]), trace_total),
        "refusal_rate": _rate(_int(traces["refused"]), trace_total),
        "feedback": feedback_total,
        "positive": _int(feedback["positive"]),
        "negative": _int(feedback["negative"]),
        "negative_rate": _rate(_int(feedback["negative"]), feedback_total),
        # 窗口内的反馈可能指向窗口外的回答，按 100% 封顶。
        "feedback_coverage": min(1.0, _rate(_int(feedback["covered"]), answers)),
        "answers_with_sources": answers_with_sources,
        "citation_clicks": _int(clicks["clicks"]),
        "citation_clicked_answers": _int(clicks["clicked"]),
        "citation_click_rate": min(
            1.0, _rate(_int(clicks["clicked"]), answers_with_sources)
        ),
    }


def timeseries(days=DEFAULT_DAYS):
    days = _days(days)
    since = _since(days)
    with db.connect() as conn:
        traces = conn.execute(
            """SELECT date(created_at) AS day, COUNT(*) AS answers,
                      SUM(CASE WHEN grounded = 1 THEN 1 ELSE 0 END) AS grounded,
                      SUM(CASE WHEN grounded = 0 THEN 1 ELSE 0 END) AS refusals
               FROM answer_traces WHERE created_at >= ?
               GROUP BY day""",
            (since,),
        ).fetchall()
        feedback = conn.execute(
            """SELECT date(created_at) AS day, COUNT(*) AS feedback,
                      SUM(CASE WHEN sentiment = 'negative' THEN 1 ELSE 0 END) AS negative
               FROM feedback WHERE created_at >= ?
               GROUP BY day""",
            (since,),
        ).fetchall()

    merged = {}
    for row in traces:
        merged[row["day"]] = {
            "day": row["day"],
            "answers": _int(row["answers"]),
            "grounded": _int(row["grounded"]),
            "refusals": _int(row["refusals"]),
            "feedback": 0,
            "negative": 0,
        }
    for row in feedback:
        item = merged.setdefault(
            row["day"],
            {"day": row["day"], "answers": 0, "grounded": 0, "refusals": 0,
             "feedback": 0, "negative": 0},
        )
        item["feedback"] = _int(row["feedback"])
        item["negative"] = _int(row["negative"])

    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date()
    return [
        merged.get(
            (start + timedelta(days=offset)).isoformat(),
            {
                "day": (start + timedelta(days=offset)).isoformat(),
                "answers": 0, "grounded": 0, "refusals": 0,
                "feedback": 0, "negative": 0,
            },
        )
        for offset in range(days)
    ]


def libraries(days=DEFAULT_DAYS):
    since = _since(days)
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT c.library,
                      COUNT(DISTINCT t.answer_id) AS answers,
                      COUNT(*) AS selected_chunks
               FROM retrieval_candidates c
               JOIN answer_traces t ON t.trace_id = c.trace_id
               WHERE c.selected = 1 AND c.library <> '' AND t.created_at >= ?
               GROUP BY c.library
               ORDER BY answers DESC, c.library""",
            (since,),
        ).fetchall()
        negatives = conn.execute(
            """SELECT c.library, COUNT(DISTINCT f.id) AS negative
               FROM feedback f
               JOIN answer_traces t ON t.answer_id = f.answer_id
               JOIN retrieval_candidates c ON c.trace_id = t.trace_id AND c.selected = 1
               WHERE f.sentiment = 'negative' AND f.created_at >= ? AND c.library <> ''
               GROUP BY c.library""",
            (since,),
        ).fetchall()
        clicks = conn.execute(
            """SELECT library, COUNT(DISTINCT answer_id) AS clicks
               FROM source_clicks
               WHERE created_at >= ? AND library <> ''
               GROUP BY library""",
            (since,),
        ).fetchall()

    negative_map = {row["library"]: _int(row["negative"]) for row in negatives}
    click_map = {row["library"]: _int(row["clicks"]) for row in clicks}
    return [
        {
            "library": row["library"],
            "answers": _int(row["answers"]),
            "selected_chunks": _int(row["selected_chunks"]),
            "negative": negative_map.get(row["library"], 0),
            "clicks": click_map.get(row["library"], 0),
        }
        for row in rows
    ]


def reasons(days=DEFAULT_DAYS):
    since = _since(days)
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT reasons_json FROM feedback
               WHERE sentiment = 'negative' AND created_at >= ?""",
            (since,),
        ).fetchall()
    counts = Counter()
    for row in rows:
        try:
            values = json.loads(row["reasons_json"] or "[]")
        except (TypeError, ValueError):
            values = []
        for value in values:
            counts[str(value)] += 1
    return [{"reason": key, "count": count} for key, count in counts.most_common()]


def categories(days=DEFAULT_DAYS):
    since = _since(days)
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT COALESCE(NULLIF(triage_category, ''), 'unknown') AS category,
                      COUNT(*) AS count
               FROM feedback WHERE created_at >= ?
               GROUP BY category ORDER BY count DESC""",
            (since,),
        ).fetchall()
    return [{"category": row["category"], "count": _int(row["count"])} for row in rows]


def _tokens(text):
    value = (text or "").lower()
    cjk = "".join(re.findall(r"[一-鿿]", value))
    bigrams = {cjk[index:index + 2] for index in range(max(0, len(cjk) - 1))}
    words = set(re.findall(r"[a-z0-9_]+", value))
    return bigrams | words


def _jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _cluster_rows(rows, threshold=CLUSTER_THRESHOLD):
    clusters = []
    for row in rows:
        tokens = _tokens(row.get("question", ""))
        if not tokens:
            continue
        best = None
        best_score = 0.0
        for cluster in clusters:
            score = _jaccard(tokens, cluster["tokens"])
            if score > best_score:
                best = cluster
                best_score = score
        if best is not None and best_score >= threshold:
            best["tokens"] |= tokens
            best["questions"].append(row.get("question", ""))
            best["reasons"].update(row.get("reasons") or [])
            best["ids"].append(row.get("id"))
        else:
            clusters.append(
                {
                    "tokens": set(tokens),
                    "questions": [row.get("question", "")],
                    "reasons": Counter(row.get("reasons") or []),
                    "ids": [row.get("id")],
                }
            )
    return clusters


def clusters(days=DEFAULT_DAYS, limit=20):
    since = _since(days)
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT f.id, a.question, f.reasons_json
               FROM feedback f
               LEFT JOIN answers a ON a.id = f.answer_id
               WHERE f.sentiment = 'negative' AND f.created_at >= ?""",
            (since,),
        ).fetchall()
    parsed = []
    for row in rows:
        try:
            reasons = json.loads(row["reasons_json"] or "[]")
        except (TypeError, ValueError):
            reasons = []
        parsed.append(
            {"id": row["id"], "question": row["question"] or "", "reasons": reasons}
        )

    items = []
    for cluster in _cluster_rows(parsed):
        questions = cluster["questions"]
        label = Counter(questions).most_common(1)[0][0] if questions else "未命名问题"
        items.append(
            {
                "label": label[:60],
                "size": len(cluster["ids"]),
                "questions": questions[:5],
                "reasons": [
                    {"reason": reason, "count": count}
                    for reason, count in cluster["reasons"].most_common(5)
                ],
            }
        )
    items.sort(key=lambda item: item["size"], reverse=True)
    return items[:max(1, min(100, int(limit or 20)))]
