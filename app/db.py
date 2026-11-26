"""SQLite 持久化层。

负责账号与会话、每日额度、对话与回答、反馈与检索轨迹、权限申请，
以及供 BM25 使用的文档切块索引。

所有表由 init_db() 幂等创建；旧库通过 ALTER TABLE 补列，并在启动时回填对话。
这里只存文本和元数据，向量不在这里——见 store.py。
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

_DB_PATH = Path(config.DB_PATH)
PERMISSION_CATALOG = (
    {"key": "ops", "name": "运维", "description": "服务器、网络、安全与发布运维资料"},
    {"key": "ai", "name": "人工智能", "description": "模型、Agent、提示词与知识库资料"},
    {"key": "dev", "name": "开发", "description": "产品研发、代码规范与工程技术资料"},
    {"key": "ops_business", "name": "运营", "description": "业务流程、客户服务与运营规范资料"},
    {"key": "hr", "name": "HR", "description": "人事制度、招聘、培训与员工服务资料"},
)
PERMISSION_KEYS = {item["key"] for item in PERMISSION_CATALOG}
# 全员可读，不出现在可申请目录里，提问时也不计入每日次数。
# 写权限只给管理员，见 app/main.py 的 _require_write_library。
COMMON_LIBRARY = "common"


# ---- 时间与会话 ----


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    # 每日次数按东八区自然日计算，不跟 UTC 日期走。
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def _conversation_title(question):
    text = " ".join((question or "").split())
    if not text:
        return "未命名对话"
    if len(text) <= 28:
        return text
    return text[:28] + "…"


def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # 允许读写并发，减少“database is locked”
    conn.execute("PRAGMA foreign_keys=ON")    # FK 是连接级开关，不设则 CASCADE 不生效
    return conn


@contextmanager
def connect():
    """供 feedback/trace/eval 等独立存储模块复用：退出时提交并关闭连接。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now():
    return _now()


def _table_exists(conn, name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row)


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn, table, name, ddl):
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _archive_table(conn, old, archive):
    """把已停用的表改名到 legacy_*；两边都存在时先并数据再删旧表。"""
    if not _table_exists(conn, old):
        return False
    if not _table_exists(conn, archive):
        conn.execute(f"ALTER TABLE {old} RENAME TO {archive}")
        return True
    shared = sorted(_columns(conn, old) & _columns(conn, archive))
    if not shared:
        return False
    names = ", ".join(shared)
    conn.execute(f"INSERT OR IGNORE INTO {archive}({names}) SELECT {names} FROM {old}")
    conn.execute(f"DROP TABLE {old}")
    return True


def _load_json(value, fallback):
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _dump_json(value):
    return json.dumps(value, ensure_ascii=False)


# ---- 启动建表与迁移 ----


def init_db():
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS daily_usage (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                usage_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            );
            CREATE TABLE IF NOT EXISTS answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_answers_user ON answers(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER NOT NULL UNIQUE REFERENCES answers(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                reason TEXT NOT NULL DEFAULT '',
                sentiment TEXT NOT NULL DEFAULT '',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                comment TEXT NOT NULL DEFAULT '',
                corrected_answer TEXT NOT NULL DEFAULT '',
                trace_id TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                triage_category TEXT NOT NULL DEFAULT '',
                triage_confidence REAL NOT NULL DEFAULT 0,
                triage_note TEXT NOT NULL DEFAULT '',
                triaged_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                triaged_at TEXT,
                updated_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                actor_type TEXT NOT NULL DEFAULT 'user',
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_revisions_feedback ON feedback_revisions(feedback_id, id);
            CREATE TABLE IF NOT EXISTS feedback_source_marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                source_index INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                heading TEXT NOT NULL DEFAULT '',
                mark TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(feedback_id, source_index, mark)
            );
            CREATE TABLE IF NOT EXISTS feedback_triage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                from_status TEXT NOT NULL DEFAULT '',
                to_status TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS content_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT '',
                heading TEXT NOT NULL DEFAULT '',
                library TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'doc_fix',
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'open',
                owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                feedback_id INTEGER REFERENCES feedback(id) ON DELETE SET NULL,
                eval_run_id INTEGER,
                resolution_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_content_tasks_status
                ON content_tasks(status, priority, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_content_tasks_source
                ON content_tasks(source, heading);
            CREATE TABLE IF NOT EXISTS content_task_feedback (
                task_id INTEGER NOT NULL REFERENCES content_tasks(id) ON DELETE CASCADE,
                feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY (task_id, feedback_id)
            );
            CREATE INDEX IF NOT EXISTS idx_content_task_feedback_feedback
                ON content_task_feedback(feedback_id);
            CREATE TABLE IF NOT EXISTS curated_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER UNIQUE REFERENCES answers(id) ON DELETE CASCADE,
                feedback_id INTEGER REFERENCES feedback(id) ON DELETE SET NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                sources_json TEXT NOT NULL DEFAULT '[]',
                library TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'candidate',
                use_as_few_shot INTEGER NOT NULL DEFAULT 0,
                eval_passed INTEGER NOT NULL DEFAULT 0,
                eval_run_id INTEGER,
                reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_curated_status
                ON curated_examples(status, use_as_few_shot, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_curated_library
                ON curated_examples(library);
            CREATE TABLE IF NOT EXISTS eval_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                dataset TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL DEFAULT '{}',
                aggregate_json TEXT NOT NULL DEFAULT '{}',
                passed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_eval_runs_created
                ON eval_runs(created_at DESC);
            CREATE TABLE IF NOT EXISTS eval_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
                case_id TEXT NOT NULL,
                answerable INTEGER NOT NULL DEFAULT 1,
                grounded INTEGER,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(run_id, case_id)
            );
            CREATE INDEX IF NOT EXISTS idx_eval_results_run
                ON eval_results(run_id);
            CREATE TABLE IF NOT EXISTS experiments (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                assignment_unit TEXT NOT NULL DEFAULT 'user',
                guardrails_json TEXT NOT NULL DEFAULT '{}',
                start_at TEXT,
                end_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_key TEXT NOT NULL REFERENCES experiments(key) ON DELETE CASCADE,
                variant_key TEXT NOT NULL,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                traffic_pct INTEGER NOT NULL DEFAULT 0,
                is_control INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(experiment_key, variant_key)
            );
            CREATE TABLE IF NOT EXISTS experiment_assignments (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                experiment_key TEXT NOT NULL REFERENCES experiments(key) ON DELETE CASCADE,
                variant_key TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, experiment_key)
            );
            CREATE INDEX IF NOT EXISTS idx_experiment_assignments_variant
                ON experiment_assignments(experiment_key, variant_key);
            CREATE TABLE IF NOT EXISTS source_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                answer_id INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                source TEXT NOT NULL DEFAULT '',
                heading TEXT NOT NULL DEFAULT '',
                anchor TEXT NOT NULL DEFAULT '',
                library TEXT NOT NULL DEFAULT '',
                source_index INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(answer_id, user_id, source, heading)
            );
            CREATE INDEX IF NOT EXISTS idx_source_clicks_created
                ON source_clicks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_source_clicks_library
                ON source_clicks(library, created_at DESC);
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created
                ON admin_audit_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action
                ON admin_audit_log(action, created_at DESC);
            CREATE TABLE IF NOT EXISTS answer_traces (
                trace_id TEXT PRIMARY KEY,
                answer_id INTEGER UNIQUE REFERENCES answers(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
                question TEXT NOT NULL,
                queries_json TEXT NOT NULL DEFAULT '[]',
                retrieval_query TEXT NOT NULL DEFAULT '',
                query_rewrites INTEGER NOT NULL DEFAULT 0,
                libraries_json TEXT NOT NULL DEFAULT '[]',
                grounded INTEGER NOT NULL DEFAULT 0,
                refusal_reason TEXT NOT NULL DEFAULT '',
                vector_hits INTEGER NOT NULL DEFAULT 0,
                bm25_hits INTEGER NOT NULL DEFAULT 0,
                reranked INTEGER NOT NULL DEFAULT 0,
                top_k INTEGER NOT NULL DEFAULT 0,
                best_vector_score REAL,
                best_bm25_score REAL,
                best_rerank_score REAL,
                config_json TEXT NOT NULL DEFAULT '{}',
                model TEXT NOT NULL DEFAULT '',
                prompt_version TEXT NOT NULL DEFAULT '',
                experiment_json TEXT NOT NULL DEFAULT '{}',
                timings_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_traces_created ON answer_traces(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traces_user ON answer_traces(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traces_grounded ON answer_traces(grounded, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traces_refusal ON answer_traces(refusal_reason, created_at DESC);
            CREATE TABLE IF NOT EXISTS retrieval_candidates (
                trace_id TEXT NOT NULL REFERENCES answer_traces(trace_id) ON DELETE CASCADE,
                rank INTEGER NOT NULL,
                chunk_id TEXT NOT NULL,
                source TEXT NOT NULL,
                heading TEXT NOT NULL DEFAULT '',
                library TEXT NOT NULL DEFAULT '',
                vector_score REAL,
                bm25_score REAL,
                rrf_score REAL,
                rerank_score REAL,
                vector_rank INTEGER,
                bm25_rank INTEGER,
                rrf_rank INTEGER,
                selected INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (trace_id, rank)
            );
            CREATE INDEX IF NOT EXISTS idx_candidates_chunk ON retrieval_candidates(chunk_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_source ON retrieval_candidates(source, heading);
            CREATE INDEX IF NOT EXISTS idx_candidates_library ON retrieval_candidates(library);
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS permission_catalog (
                permission_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS permission_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission_key TEXT NOT NULL REFERENCES permission_catalog(permission_key) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
                requested_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE(user_id, permission_key)
            );
            CREATE INDEX IF NOT EXISTS idx_permission_requests_status ON permission_requests(status, requested_at DESC);
            CREATE TABLE IF NOT EXISTS search_chunks (
                chunk_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                heading TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                library TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_search_chunks_source ON search_chunks(source);
            CREATE INDEX IF NOT EXISTS idx_search_chunks_library ON search_chunks(library);
            CREATE VIRTUAL TABLE IF NOT EXISTS search_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source,
                title,
                heading,
                text,
                library UNINDEXED,
                tokenize = 'unicode61'
            );
            """
        )
        # 以下是给老库补列、补数据的迁移。新库建表时已包含这些列，
        # 所以每次启动都先查 PRAGMA table_info，保证重复执行安全。
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        if "display_name" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        if "avatar" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")
        if "profile_edit_month" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN profile_edit_month TEXT NOT NULL DEFAULT ''")
        if "profile_edit_count" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN profile_edit_count INTEGER NOT NULL DEFAULT 0")
        answer_columns = {row["name"] for row in conn.execute("PRAGMA table_info(answers)").fetchall()}
        if "conversation_id" not in answer_columns:
            conn.execute("ALTER TABLE answers ADD COLUMN conversation_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_answers_conversation ON answers(conversation_id, id)")
        orphans = conn.execute(
            "SELECT id, user_id, question, created_at FROM answers WHERE conversation_id IS NULL ORDER BY id"
        ).fetchall()
        for row in orphans:
            cur = conn.execute(
                "INSERT INTO conversations(user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (row["user_id"], _conversation_title(row["question"]), row["created_at"], row["created_at"]),
            )
            conn.execute("UPDATE answers SET conversation_id = ? WHERE id = ?", (cur.lastrowid, row["id"]))
        # 阶段 1：feedback 从 1-5 星扩展为“情感 + 原因 + 轨迹关联”。
        # 保留 rating 列，旧数据按 5 星=正向、1-4 星=负向回填。
        for name, ddl in (
            ("sentiment", "TEXT NOT NULL DEFAULT ''"),
            ("reasons_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("comment", "TEXT NOT NULL DEFAULT ''"),
            ("corrected_answer", "TEXT NOT NULL DEFAULT ''"),
            ("trace_id", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'new'"),
            ("triage_category", "TEXT NOT NULL DEFAULT ''"),
            ("triage_confidence", "REAL NOT NULL DEFAULT 0"),
            ("triage_note", "TEXT NOT NULL DEFAULT ''"),
            ("triaged_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL"),
            ("triaged_at", "TEXT"),
            ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            _add_column(conn, "feedback", name, ddl)
        conn.execute(
            "UPDATE feedback SET sentiment = CASE WHEN rating >= 5 THEN 'positive' ELSE 'negative' END "
            "WHERE sentiment = ''"
        )
        conn.execute("UPDATE feedback SET comment = reason WHERE comment = '' AND reason <> ''")
        conn.execute(
            "UPDATE feedback SET reasons_json = '[\"other\"]' "
            "WHERE sentiment = 'negative' AND reasons_json = '[]'"
        )
        conn.execute("UPDATE feedback SET updated_at = created_at WHERE updated_at = ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_sentiment ON feedback(sentiment, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_trace ON feedback(trace_id)")
        _add_column(conn, "curated_examples", "eval_passed", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "curated_examples", "eval_run_id", "INTEGER")
        conn.execute("PRAGMA user_version = 10")
        conn.execute(
            "INSERT INTO schema_meta(key, value, updated_at) VALUES ('schema_version', '10', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (_now(),),
        )
        for item in PERMISSION_CATALOG:
            conn.execute(
                "INSERT INTO permission_catalog(permission_key, name, description) VALUES (?, ?, ?) ON CONFLICT(permission_key) DO UPDATE SET name=excluded.name, description=excluded.description",
                (item["key"], item["name"], item["description"]),
            )
        # 旧记忆表已无读写点，改名归档，主库不再保留。
        _archive_table(conn, "assistant_memory", "legacy_assistant_memory")
        _archive_table(conn, "learning_notes", "legacy_learning_notes")
        _rebuild_fts_index(conn)


def _fts_terms(value):
    """将中文拆成二元词，避免 SQLite unicode61 把整段中文当成一个词。"""
    terms = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", (value or "").lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            if len(part) == 1:
                terms.append(part)
            else:
                terms.extend(part[i:i + 2] for i in range(len(part) - 1))
        else:
            terms.append(part)
    return list(dict.fromkeys(terms))


def _fts_index_text(value):
    return " ".join(_fts_terms(value))


def _fts_query(value):
    terms = _fts_terms(value)
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)


def _rebuild_fts_index(conn):
    """search_chunks_fts 是派生索引，启动时全量重建以兼容旧版本索引。

    当前文档量下可接受，切块数量级上到万级时应改为增量维护。
    """
    conn.execute("DELETE FROM search_chunks_fts")
    rows = conn.execute("SELECT chunk_id, source, title, heading, text, library FROM search_chunks").fetchall()
    conn.executemany(
        """INSERT INTO search_chunks_fts(chunk_id, source, title, heading, text, library)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (row["chunk_id"], _fts_index_text(row["source"]), _fts_index_text(row["title"]),
             _fts_index_text(row["heading"]), _fts_index_text(row["text"]), row["library"])
            for row in rows
        ],
    )


def _hash_password(password):
    """PBKDF2-HMAC-SHA256，16 字节随机盐，310,000 次迭代。

    存储格式：pbkdf2_sha256$迭代次数$盐$摘要。
    迭代次数写进字符串而不是写死在校验逻辑里，这样以后提高参数，
    旧密码仍然能按原次数校验。
    """
    salt = secrets.token_bytes(16)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_password(password, encoded):
    # 用 compare_digest 而不是 ==，避免通过响应时间逐字节推断摘要。
    # 任何格式错误都返回 False。
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _user_dict(row, include_permissions=False):
    result = {"id": row["id"], "username": row["username"], "role": row["role"]}
    if include_permissions:
        result["permissions"] = approved_permissions(row["id"])
    return result


def create_user(username, password, role="user"):
    username = username.strip()
    with _connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, _hash_password(password), role, _now()),
            )
        except sqlite3.IntegrityError:
            return None
        return {"id": cur.lastrowid, "username": username, "role": role, "permissions": []}


def authenticate(username, password):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    # 用户不存在和密码错误都返回 None，调用方不能从结果区分这两种失败。
    if not row or not _verify_password(password, row["password_hash"]):
        return None
    return _user_dict(row, include_permissions=True)


def create_session(user_id, days=14):
    # token 本身就是凭据，数据库只存 token；过期后由 get_user_by_session 惰性删除。
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions(token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, expires, _now()),
        )
    return token


def get_user_by_session(token):
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            """SELECT u.id, u.username, u.role, s.expires_at
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return _user_dict(row, include_permissions=True)


def delete_session(token):
    if token:
        with _connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# ---- 额度 ----


def quota_status(user_id):
    """只读额度视图。管理员返回 unlimited，前端据此隐藏次数提示；扣减在 consume_quota。"""
    with _connect() as conn:
        user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and user["role"] == "admin":
        return {"used": 0, "limit": None, "remaining": None, "unlimited": True}
    with _connect() as conn:
        row = conn.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, _today()),
        ).fetchone()
    used = int(row["count"]) if row else 0
    return {"used": used, "limit": config.DAILY_ASK_LIMIT, "remaining": max(0, config.DAILY_ASK_LIMIT - used)}


def consume_quota(user_id):
    """扣一次每日额度。返回 None 表示今天已经用完。

    管理员不计数，直接返回 unlimited。
    """
    with _connect() as conn:
        user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if user and user["role"] == "admin":
        return {"used": 0, "limit": None, "remaining": None, "unlimited": True}
    today = _today()
    with _connect() as conn:
        # BEGIN IMMEDIATE 立即取写锁，让“读计数 → 判断 → 写入”成为一个原子事务。
        # 否则两个并发请求可能同时读到 used=9，都通过检查，最终写成 11。
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        used = int(row["count"]) if row else 0
        if used >= config.DAILY_ASK_LIMIT:
            return None
        if row:
            conn.execute(
                "UPDATE daily_usage SET count = count + 1 WHERE user_id = ? AND usage_date = ?",
                (user_id, today),
            )
        else:
            conn.execute(
                "INSERT INTO daily_usage(user_id, usage_date, count) VALUES (?, ?, 1)",
                (user_id, today),
            )
    used += 1
    return {"used": used, "limit": config.DAILY_ASK_LIMIT, "remaining": config.DAILY_ASK_LIMIT - used}


# ---- 对话、回答与反馈 ----


def create_answer(user_id, question, answer, sources_json, conversation_id=None):
    """保存一条问答。未指定对话时按问题新建一组；指定的对话必须属于该用户。"""
    now = _now()
    with _connect() as conn:
        if conversation_id is None:
            cur = conn.execute(
                "INSERT INTO conversations(user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, _conversation_title(question), now, now),
            )
            conversation_id = cur.lastrowid
        else:
            owned = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if not owned:
                raise ValueError("找不到这组对话")
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        cur = conn.execute(
            "INSERT INTO answers(user_id, question, answer, sources_json, created_at, conversation_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, question, answer, sources_json, now, conversation_id),
        )
        return cur.lastrowid


def conversation_id_for_answer(answer_id):
    with _connect() as conn:
        row = conn.execute("SELECT conversation_id FROM answers WHERE id = ?", (answer_id,)).fetchone()
        return row["conversation_id"] if row else None


def conversation_for_user(user_id, conversation_id):
    with _connect() as conn:
        return conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()


def list_conversations(user_id, limit=50):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.updated_at,
                   (SELECT COUNT(*) FROM answers a WHERE a.conversation_id = c.id) AS turns
            FROM conversations c
            WHERE c.user_id = ?
            ORDER BY c.updated_at DESC, c.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def conversation_messages(user_id, conversation_id):
    convo = conversation_for_user(user_id, conversation_id)
    if not convo:
        return None
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.question, a.answer, a.sources_json, a.created_at,
                   f.id AS feedback_id, f.rating, f.sentiment, f.reasons_json,
                   f.comment, f.corrected_answer, f.status
            FROM answers a
            LEFT JOIN feedback f ON f.answer_id = a.id
            WHERE a.user_id = ? AND a.conversation_id = ?
            ORDER BY a.id ASC
            """,
            (user_id, conversation_id),
        ).fetchall()
    return convo, rows


def delete_conversation(user_id, conversation_id):
    with _connect() as conn:
        owned = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone()
        if not owned:
            return False
        conn.execute(
            "DELETE FROM answers WHERE user_id = ? AND conversation_id = ?",
            (user_id, conversation_id),
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        )
        return True


def answer_for_user(answer_id, user_id):
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM answers WHERE id = ? AND user_id = ?", (answer_id, user_id)
        ).fetchone()


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


def save_feedback(answer_id, user_id, rating, reason="", *, sentiment="", reasons=None,
                  comment="", corrected_answer="", source_marks=None):
    """兼容旧调用的同时写入情感、原因和来源标记。"""
    now = _now()
    sentiment = sentiment or ("positive" if rating is not None and rating >= 5 else "negative")
    rating = int(rating) if rating is not None else (5 if sentiment == "positive" else 1)
    comment = comment or reason or ""
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
                answer_id, user_id, rating, reason, sentiment, reasons_json, comment,
                corrected_answer, trace_id, status, updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (
                answer_id,
                user_id,
                rating,
                reason,
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
            f"""SELECT f.id, f.created_at, u.username, a.question,
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


def recent_answers(user_id, limit=5, conversation_id=None):
    with _connect() as conn:
        if conversation_id is None:
            return conn.execute(
                "SELECT question, answer, created_at FROM answers WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return conn.execute(
            "SELECT question, answer, created_at FROM answers WHERE user_id = ? AND conversation_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, conversation_id, limit),
        ).fetchall()


def list_users():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [
        {"id": row["id"], "username": row["username"], "role": row["role"],
         "created_at": row["created_at"], "quota": quota_status(row["id"]),
         "permissions": permission_statuses(row["id"])}
        for row in rows
    ]


def reset_quota(user_id):
    with _connect() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False
        conn.execute(
            "DELETE FROM daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, _today()),
        )
    return True


def delete_user(user_id, actor_id):
    """删除普通用户；禁止管理员删除自己或其他管理员账号。"""
    with _connect() as conn:
        target = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not target:
            return "not_found"
        if target["id"] == actor_id:
            return "self"
        if target["role"] == "admin":
            return "admin"
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return "deleted"


# ---- 用户资料（显示名称 / 头像，每月限改 2 次） ----

PROFILE_EDIT_LIMIT = 2


def _profile_month():
    return _today()[:7]  # YYYY-MM（UTC+8 自然月）


def get_profile(user_id):
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, display_name, avatar, profile_edit_month, profile_edit_count FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    used = row["profile_edit_count"] if row["profile_edit_month"] == _profile_month() else 0
    return {
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "avatar": row["avatar"] or None,
        "edits_used": used,
        "edits_limit": PROFILE_EDIT_LIMIT,
        "edits_left": max(0, PROFILE_EDIT_LIMIT - used),
    }


def update_profile(user_id, display_name=None, avatar=None):
    """修改显示名称 / 头像。参数为 None 表示该项不修改。

    返回 (ok, error)。内容没有任何实际变化时不消耗当月次数。"""
    with _connect() as conn:
        row = conn.execute(
            "SELECT username, display_name, avatar, profile_edit_month, profile_edit_count FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False, "用户不存在"
        current_name = row["display_name"] or row["username"]
        current_avatar = row["avatar"] or ""
        changed = (display_name is not None and display_name != current_name) or (
            avatar is not None and avatar != current_avatar
        )
        if not changed:
            return True, None
        month = _profile_month()
        used = row["profile_edit_count"] if row["profile_edit_month"] == month else 0
        if used >= PROFILE_EDIT_LIMIT:
            return False, f"本月资料修改次数已用完（每月 {PROFILE_EDIT_LIMIT} 次），下个月再试"
        new_name = display_name if display_name is not None else current_name
        new_avatar = avatar if avatar is not None else current_avatar
        conn.execute(
            "UPDATE users SET display_name = ?, avatar = ?, profile_edit_month = ?, profile_edit_count = ? WHERE id = ?",
            (new_name, new_avatar, month, used + 1, user_id),
        )
    return True, None


def set_admin(username, password):
    username = username.strip()
    with _connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = 'admin' WHERE id = ?",
                (_hash_password(password), row["id"]),
            )
            user_id = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, role, created_at) VALUES (?, ?, 'admin', ?)",
                (username, _hash_password(password), _now()),
            )
            user_id = cur.lastrowid
    return {"id": user_id, "username": username, "role": "admin", "permissions": sorted(PERMISSION_KEYS | {COMMON_LIBRARY})}


# ---- 权限 ----

def list_permissions():
    return [dict(item) for item in PERMISSION_CATALOG]


def approved_permissions(user_id):
    with _connect() as conn:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return []
        # 管理员拥有全部业务库。函数返回前会再给每个登录用户补上全员库。
        # 调用方不必各自处理 common；业务库判断请用 business_permissions。
        if row["role"] == "admin":
            keys = set(PERMISSION_KEYS)
        else:
            keys = {
                item["permission_key"]
                for item in conn.execute(
                    "SELECT permission_key FROM permission_requests WHERE user_id = ? AND status = 'approved'",
                    (user_id,),
                ).fetchall()
            }
    keys.add(COMMON_LIBRARY)
    return sorted(keys)


def business_permissions(user_id):
    # 业务库决定是否扣每日额度：只有申请过业务库的用户才消耗次数，common 不计。
    return [key for key in approved_permissions(user_id) if key != COMMON_LIBRARY]


def permission_statuses(user_id):
    with _connect() as conn:
        user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        rows = conn.execute(
            """SELECT c.permission_key, c.name, c.description,
                      COALESCE(r.status, 'none') AS status, r.id AS request_id,
                      r.requested_at, r.reviewed_at
               FROM permission_catalog c
               LEFT JOIN permission_requests r
                 ON r.permission_key = c.permission_key AND r.user_id = ?
               ORDER BY c.rowid""",
            (user_id,),
        ).fetchall()
    result = [dict(row) for row in rows]
    # 管理员在界面上统一显示为已通过，避免出现“管理员还要申请”的矛盾状态；
    # 这里只改返回给前端的展示值，不动数据库里的历史申请记录。
    if user and user["role"] == "admin":
        for item in result:
            item["status"] = "approved"
    return result


def has_permission(user_id, permission_key):
    with _connect() as conn:
        if permission_key == COMMON_LIBRARY:
            return bool(conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone())
        if permission_key not in PERMISSION_KEYS:
            return False
        user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user["role"] == "admin":
            return True
        row = conn.execute(
            "SELECT 1 FROM permission_requests WHERE user_id = ? AND permission_key = ? AND status = 'approved'",
            (user_id, permission_key),
        ).fetchone()
    return bool(row)


def request_permission(user_id, permission_key):
    if permission_key not in PERMISSION_KEYS:
        return None
    with _connect() as conn:
        # 重复申请时：已审批的记录保持 approved、原申请和审批时间不变；
        # pending / rejected 会被重置为 pending 并刷新申请时间、清空审批信息。
        # 如果简化成无脑 UPDATE，用户重新点一次“申请”就会丢掉已有权限。
        conn.execute(
            """INSERT INTO permission_requests(user_id, permission_key, status, requested_at)
               VALUES (?, ?, 'pending', ?)
               ON CONFLICT(user_id, permission_key) DO UPDATE SET
                 status = CASE WHEN permission_requests.status = 'approved' THEN 'approved' ELSE 'pending' END,
                 requested_at = CASE WHEN permission_requests.status = 'approved' THEN permission_requests.requested_at ELSE excluded.requested_at END,
                 reviewed_at = CASE WHEN permission_requests.status = 'approved' THEN permission_requests.reviewed_at ELSE NULL END,
                 reviewed_by = CASE WHEN permission_requests.status = 'approved' THEN permission_requests.reviewed_by ELSE NULL END""",
            (user_id, permission_key, _now()),
        )
        row = conn.execute(
            "SELECT * FROM permission_requests WHERE user_id = ? AND permission_key = ?",
            (user_id, permission_key),
        ).fetchone()
    return dict(row)


def list_permission_requests(status=None):
    with _connect() as conn:
        sql = """SELECT r.id, r.user_id, u.username, r.permission_key, c.name, c.description,
                         r.status, r.requested_at, r.reviewed_at, r.reviewed_by
                  FROM permission_requests r
                  JOIN users u ON u.id = r.user_id
                  JOIN permission_catalog c ON c.permission_key = r.permission_key"""
        params = []
        if status:
            sql += " WHERE r.status = ?"
            params.append(status)
        sql += " ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END, r.requested_at DESC"
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def review_permission(request_id, status, reviewer_id):
    if status not in {"approved", "rejected"}:
        return None
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE permission_requests SET status = ?, reviewed_at = ?, reviewed_by = ?
               WHERE id = ?""",
            (status, _now(), reviewer_id, request_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            """SELECT r.id, r.user_id, u.username, r.permission_key, c.name, c.description,
                      r.status, r.requested_at, r.reviewed_at, r.reviewed_by
               FROM permission_requests r JOIN users u ON u.id=r.user_id
               JOIN permission_catalog c ON c.permission_key=r.permission_key WHERE r.id = ?""",
            (request_id,),
        ).fetchone()
    return dict(row)


# ---- 混合检索的 BM25 索引 ----

def replace_search_chunks(source, chunks):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM search_chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM search_chunks WHERE source = ?)",
            (source,),
        )
        conn.execute("DELETE FROM search_chunks WHERE source = ?", (source,))
        for chunk in chunks:
            row = {
                "chunk_id": chunk["id"], "source": chunk["source"], "title": chunk.get("title", ""),
                "heading": chunk.get("heading", ""), "text": chunk.get("text", ""),
                "library": chunk.get("library", "ops_business"),
            }
            conn.execute(
                "INSERT OR REPLACE INTO search_chunks(chunk_id, source, title, heading, text, library) VALUES (:chunk_id, :source, :title, :heading, :text, :library)",
                row,
            )
            conn.execute(
                "INSERT INTO search_chunks_fts(chunk_id, source, title, heading, text, library) VALUES (?, ?, ?, ?, ?, ?)",
                (row["chunk_id"], _fts_index_text(row["source"]), _fts_index_text(row["title"]),
                 _fts_index_text(row["heading"]), _fts_index_text(row["text"]), row["library"]),
            )


def delete_search_source(source):
    with _connect() as conn:
        conn.execute(
            "DELETE FROM search_chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM search_chunks WHERE source = ?)",
            (source,),
        )
        conn.execute("DELETE FROM search_chunks WHERE source = ?", (source,))


def search_bm25(query, libraries, limit=20):
    if not libraries:
        return []
    match = _fts_query(query)
    if not match:
        return []
    placeholders = ",".join("?" for _ in libraries)
    sql = f"""SELECT f.chunk_id, c.source, c.title, c.heading, c.text, c.library,
                      bm25(search_chunks_fts) AS bm25_score
               FROM search_chunks_fts AS f
               JOIN search_chunks AS c ON c.chunk_id = f.chunk_id
               WHERE search_chunks_fts MATCH ? AND c.library IN ({placeholders})
               ORDER BY bm25_score ASC LIMIT ?"""
    with _connect() as conn:
        # 先多取 max(limit*4, 40)，因为下面的首尾锚点过滤会丢掉一部分，最后再截到 limit。
        rows = conn.execute(sql, [match, *libraries, max(limit * 4, 40)]).fetchall()
    rows = [dict(row) for row in rows]
    # 中文 FTS 使用二元词。要求命中查询首/尾锚点，避免“完全不存在的词”
    # 仅因包含一个常见二元词而被当成有效证据。
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", query.lower())
    anchors = {run[:2] for run in cjk_runs if len(run) >= 2} | {run[-2:] for run in cjk_runs if len(run) >= 2}
    if anchors:
        rows = [row for row in rows if anchors.intersection(_fts_terms(row["text"]))]
    return rows[:limit]


init_db()
