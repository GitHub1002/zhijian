"""在线实验：配置、确定性分桶、结果与护栏。

实验只允许覆盖检索参数，不碰权限、认证、额度和隐私边界。默认关闭
（EXPERIMENTS_ENABLED=0），关闭时不查库、不分桶，运行时行为完全不变。
"""
import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from . import config, db

STATUSES = {"draft", "running", "paused", "ended"}
CONFIG_LIMITS = {
    "HYBRID_TOP_K": (5, 30),
    "RRF_K": (10, 120),
    "MIN_VECTOR_SCORE": (0.2, 0.6),
    "MIN_RERANK_SCORE": (-10.0, 5.0),
    "RERANK_TOP_K": (1, 8),
    "RERANK_ENABLED": None,
}
INT_KEYS = {"HYBRID_TOP_K", "RRF_K", "RERANK_TOP_K"}
DEFAULT_GUARDRAILS = {
    "negative_rate_delta": 0.05,
    "refusal_rate_delta": 0.10,
    "p95_latency_ratio": 0.30,
}
_KEY_RE = re.compile(r"^[a-z0-9_-]{1,60}$")
_CACHE = {"at": 0.0, "items": []}


def _load_json(value, fallback):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def validate_config(values):
    if not isinstance(values, dict):
        raise ValueError("实验配置必须是 JSON 对象")
    normalized = {}
    for key, value in values.items():
        if key not in CONFIG_LIMITS:
            raise ValueError(f"不允许的实验参数：{key}")
        if key == "RERANK_ENABLED":
            if not isinstance(value, bool):
                raise ValueError("RERANK_ENABLED 必须是布尔值")
            normalized[key] = value
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 必须是数字")
        low, high = CONFIG_LIMITS[key]
        if not (low <= number <= high):
            raise ValueError(f"{key} 必须在 {low} 到 {high} 之间")
        normalized[key] = int(number) if key in INT_KEYS else number
    return normalized


def _normalize_variants(variants):
    if not variants:
        raise ValueError("至少需要一个实验变体")
    seen = set()
    controls = 0
    traffic_total = 0
    normalized = []
    for item in variants:
        key = str(item.get("variant_key") or "").strip()
        name = str(item.get("name") or "").strip() or key
        if not key or key in seen:
            raise ValueError("变体 key 不能为空且不能重复")
        seen.add(key)
        traffic = int(item.get("traffic_pct") or 0)
        if not 0 <= traffic <= 100:
            raise ValueError("流量比例必须在 0 到 100 之间")
        is_control = bool(item.get("is_control"))
        controls += 1 if is_control else 0
        traffic_total += traffic
        normalized.append(
            {
                "variant_key": key,
                "name": name,
                "config": validate_config(item.get("config") or {}),
                "traffic_pct": traffic,
                "is_control": is_control,
            }
        )
    if controls != 1:
        raise ValueError("必须且只能有一个对照组")
    if traffic_total > 100:
        raise ValueError("所有变体流量之和不能超过 100%")
    if not any(item["is_control"] and item["traffic_pct"] > 0 for item in normalized):
        raise ValueError("对照组流量必须大于 0")
    return normalized


def _variants(conn, experiment_key):
    rows = conn.execute(
        """SELECT * FROM experiment_variants
           WHERE experiment_key = ? ORDER BY id""",
        (experiment_key,),
    ).fetchall()
    return [
        {
            "variant_key": row["variant_key"],
            "name": row["name"],
            "config": _load_json(row["config_json"], {}),
            "traffic_pct": row["traffic_pct"],
            "is_control": bool(row["is_control"]),
        }
        for row in rows
    ]


def _experiment_dict(conn, row):
    item = dict(row)
    item["guardrails"] = _load_json(item.pop("guardrails_json", "{}"), {})
    item["variants"] = _variants(conn, row["key"])
    return item


def list_experiments():
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM experiments ORDER BY created_at DESC, key"
        ).fetchall()
        return [_experiment_dict(conn, row) for row in rows]


def get_experiment(key):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE key = ?", (key,)).fetchone()
        return _experiment_dict(conn, row) if row else None


def create_experiment(key, name, description="", variants=None, guardrails=None):
    key = (key or "").strip()
    if not _KEY_RE.fullmatch(key):
        raise ValueError("实验 key 只能包含小写字母、数字、下划线和连字符")
    variants = _normalize_variants(variants)
    guardrails = {**DEFAULT_GUARDRAILS, **(guardrails or {})}
    now = db.now()
    with db.connect() as conn:
        try:
            conn.execute(
                """INSERT INTO experiments(
                    key, name, description, status, assignment_unit,
                    guardrails_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'draft', 'user', ?, ?, ?)""",
                (key, name, description or "", json.dumps(guardrails, ensure_ascii=False), now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("实验 key 已存在")
        for item in variants:
            conn.execute(
                """INSERT INTO experiment_variants(
                    experiment_key, variant_key, name, config_json,
                    traffic_pct, is_control, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    item["variant_key"],
                    item["name"],
                    json.dumps(item["config"], ensure_ascii=False),
                    item["traffic_pct"],
                    1 if item["is_control"] else 0,
                    now,
                ),
            )
    refresh_cache()
    return get_experiment(key)


def update_experiment(key, *, status=None, variants=None, guardrails=None):
    updates = {}
    if status is not None:
        if status not in STATUSES:
            raise ValueError("未知实验状态")
        updates["status"] = status
        if status == "running":
            updates["start_at"] = db.now()
        if status == "ended":
            updates["end_at"] = db.now()
    if guardrails is not None:
        updates["guardrails_json"] = json.dumps(
            {**DEFAULT_GUARDRAILS, **guardrails}, ensure_ascii=False
        )
    updates["updated_at"] = db.now()
    normalized = _normalize_variants(variants) if variants is not None else None
    with db.connect() as conn:
        if not conn.execute("SELECT 1 FROM experiments WHERE key = ?", (key,)).fetchone():
            return None
        assignments = ", ".join(f"{name} = ?" for name in updates)
        conn.execute(
            f"UPDATE experiments SET {assignments} WHERE key = ?",
            [*updates.values(), key],
        )
        if normalized is not None:
            conn.execute("DELETE FROM experiment_variants WHERE experiment_key = ?", (key,))
            now = db.now()
            for item in normalized:
                conn.execute(
                    """INSERT INTO experiment_variants(
                        experiment_key, variant_key, name, config_json,
                        traffic_pct, is_control, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        key,
                        item["variant_key"],
                        item["name"],
                        json.dumps(item["config"], ensure_ascii=False),
                        item["traffic_pct"],
                        1 if item["is_control"] else 0,
                        now,
                    ),
                )
    refresh_cache()
    return get_experiment(key)


def refresh_cache():
    _CACHE["at"] = 0.0
    _CACHE["items"] = []


def _load_active():
    now = db.now()
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT * FROM experiments
               WHERE status = 'running'
                 AND (start_at IS NULL OR start_at <= ?)
                 AND (end_at IS NULL OR end_at >= ?)""",
            (now, now),
        ).fetchall()
        return [_experiment_dict(conn, row) for row in rows]


def _active():
    if not config.EXPERIMENTS_ENABLED:
        return []
    now = time.monotonic()
    if now - _CACHE["at"] < config.EXPERIMENT_CACHE_SECONDS:
        return _CACHE["items"]
    items = _load_active()
    _CACHE["at"] = now
    _CACHE["items"] = items
    return items


def _assign(user_id, experiment):
    with db.connect() as conn:
        existing = conn.execute(
            """SELECT variant_key FROM experiment_assignments
               WHERE user_id = ? AND experiment_key = ?""",
            (user_id, experiment["key"]),
        ).fetchone()
        if existing:
            for variant in experiment["variants"]:
                if variant["variant_key"] == existing["variant_key"]:
                    return variant
            return None

        bucket = int(
            hashlib.sha256(f"{experiment['key']}:{user_id}".encode()).hexdigest(), 16
        ) % 100
        cumulative = 0
        for variant in experiment["variants"]:
            cumulative += variant["traffic_pct"]
            if bucket < cumulative:
                conn.execute(
                    """INSERT OR IGNORE INTO experiment_assignments(
                        user_id, experiment_key, variant_key, assigned_at
                    ) VALUES (?, ?, ?, ?)""",
                    (user_id, experiment["key"], variant["variant_key"], db.now()),
                )
                return variant
    return None


def resolve_retrieval_config(user_id):
    """返回 (检索参数覆盖, {实验: 变体})；实验关闭时是空字典。"""
    merged = {}
    meta = {}
    for experiment in _active():
        variant = _assign(user_id, experiment)
        if not variant:
            continue
        meta[experiment["key"]] = variant["variant_key"]
        merged.update(variant["config"])
    return merged, meta


def _p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]


def _variant_metrics(conn, key, variant_key, since):
    assignments = conn.execute(
        """SELECT COUNT(*) AS n FROM experiment_assignments
           WHERE experiment_key = ? AND variant_key = ?""",
        (key, variant_key),
    ).fetchone()["n"]
    traces = conn.execute(
        """SELECT t.grounded, t.timings_json
           FROM answer_traces t
           JOIN experiment_assignments a
             ON a.user_id = t.user_id AND a.experiment_key = ?
           WHERE a.variant_key = ? AND t.created_at >= ?""",
        (key, variant_key, since),
    ).fetchall()
    feedback = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN f.sentiment = 'negative' THEN 1 ELSE 0 END) AS negative
           FROM feedback f
           JOIN experiment_assignments a
             ON a.user_id = f.user_id AND a.experiment_key = ?
           WHERE a.variant_key = ? AND f.created_at >= ?""",
        (key, variant_key, since),
    ).fetchone()

    trace_total = len(traces)
    refusals = sum(1 for row in traces if not row["grounded"])
    latencies = []
    for row in traces:
        timings = _load_json(row["timings_json"], {})
        value = timings.get("prepare_ms")
        if isinstance(value, (int, float)):
            latencies.append(float(value))
    feedback_total = int(feedback["total"] or 0)
    negative = int(feedback["negative"] or 0)
    return {
        "assignments": int(assignments),
        "answers": trace_total,
        "refusals": refusals,
        "refusal_rate": round(refusals / trace_total, 4) if trace_total else None,
        "feedback": feedback_total,
        "negative": negative,
        "negative_rate": round(negative / feedback_total, 4) if feedback_total else None,
        "p95_latency_ms": _p95(latencies),
    }


def _guardrail_flags(control, variant, settings):
    flags = []
    if control["negative_rate"] is not None and variant["negative_rate"] is not None:
        delta = variant["negative_rate"] - control["negative_rate"]
        if delta > float(settings.get("negative_rate_delta", 0.05)):
            flags.append(f"负面率比对照高 {delta:.4f}")
    if control["refusal_rate"] is not None and variant["refusal_rate"] is not None:
        delta = variant["refusal_rate"] - control["refusal_rate"]
        if delta > float(settings.get("refusal_rate_delta", 0.10)):
            flags.append(f"拒答率比对照高 {delta:.4f}")
    if control["p95_latency_ms"] and variant["p95_latency_ms"]:
        ratio = variant["p95_latency_ms"] / control["p95_latency_ms"] - 1
        if ratio > float(settings.get("p95_latency_ratio", 0.30)):
            flags.append(f"p95 延迟比对照高 {ratio:.2%}")
    return flags


def experiment_results(key, days=14):
    experiment = get_experiment(key)
    if not experiment:
        return None
    days = max(1, min(365, int(days or 14)))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.connect() as conn:
        metrics = {
            variant["variant_key"]: _variant_metrics(
                conn, key, variant["variant_key"], since
            )
            for variant in experiment["variants"]
        }
    control = next(
        (variant for variant in experiment["variants"] if variant["is_control"]), None
    )
    control_metrics = metrics.get(control["variant_key"]) if control else None
    variants = []
    for variant in experiment["variants"]:
        item = {**variant, **metrics[variant["variant_key"]]}
        item["guardrail_flags"] = []
        if control and not variant["is_control"]:
            item["guardrail_flags"] = _guardrail_flags(
                control_metrics, metrics[variant["variant_key"]], experiment["guardrails"]
            )
        item["guardrail_breached"] = bool(item["guardrail_flags"])
        variants.append(item)
    return {
        "experiment": experiment,
        "days": days,
        "control": control["variant_key"] if control else None,
        "variants": variants,
    }
