"""FastAPI 应用与 HTTP 层。

负责路由、Cookie 会话、权限依赖、文档 CRUD/上传/同步，以及把 RAG 结果
转成 JSON 或 SSE。业务规则尽量下沉到 db.py / rag.py，这里只做参数校验、
权限判断和错误映射。
"""
import csv
import io
import json
import logging
import re
import sqlite3
import mimetypes
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

from . import analytics, audit, config, content, content_store, curated_store, db, documents, eval_store, experiments, feedback as feedback_rules, ingest, llm, md_render, observability, rag, rate_limit, tracing

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# 字体与常用前端资源的 MIME 修正，避免被识别为 octet-stream 导致浏览器拒绝加载
for _ext, _mime in ((".ttf", "font/ttf"), (".woff", "font/woff"), (".woff2", "font/woff2"), (".otf", "font/otf")):
    mimetypes.add_type(_mime, _ext)
@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="智检", lifespan=lifespan)
app.middleware("http")(observability.middleware)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# 请求体模型只做粗粒度的格式/长度校验；权限、路径和业务状态在路由里判断。
class AuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=128)


class AskRequest(BaseModel):
    question: str
    conversation_id: Optional[int] = None


class FeedbackSourceMark(BaseModel):
    source_index: int = Field(ge=1, le=50)
    mark: Literal["wrong_citation", "irrelevant", "outdated", "missing_context"]


class FeedbackRequest(BaseModel):
    answer_id: int
    sentiment: Literal["positive", "negative"]
    reasons: list[str] = Field(default_factory=list)
    comment: str = Field(default="", max_length=2000)
    corrected_answer: str = Field(default="", max_length=4000)
    source_marks: list[FeedbackSourceMark] = Field(default_factory=list, max_length=20)
    client_version: str = Field(default="", max_length=40)


class FeedbackUpdateRequest(BaseModel):
    sentiment: Optional[Literal["positive", "negative"]] = None
    reasons: Optional[list[str]] = None
    comment: Optional[str] = Field(default=None, max_length=2000)
    corrected_answer: Optional[str] = Field(default=None, max_length=4000)
    source_marks: Optional[list[FeedbackSourceMark]] = None


class FeedbackTriageRequest(BaseModel):
    status: Literal["new", "triaged", "in_progress", "resolved", "dismissed"]
    category: str
    note: str = Field(default="", max_length=2000)


class SourceClickRequest(BaseModel):
    answer_id: int
    source: str = Field(default="", max_length=300)
    heading: str = Field(default="", max_length=300)
    anchor: str = Field(default="", max_length=300)
    library: str = Field(default="", max_length=40)
    source_index: int = Field(default=0, ge=0, le=50)


class ContentTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    source: str = Field(default="", max_length=300)
    heading: str = Field(default="", max_length=300)
    library: str = Field(default="", max_length=40)
    kind: str = "doc_fix"
    priority: str = "medium"
    owner_id: Optional[int] = None
    eval_run_id: Optional[int] = None


class ContentTaskUpdateRequest(BaseModel):
    status: Optional[Literal["open", "in_progress", "resolved", "dismissed"]] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    kind: Optional[str] = None
    owner_id: Optional[int] = None
    eval_run_id: Optional[int] = None
    resolution_note: Optional[str] = Field(default=None, max_length=2000)


class ContentTaskFromFeedbackRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=4000)
    source: Optional[str] = Field(default=None, max_length=300)
    heading: Optional[str] = Field(default=None, max_length=300)
    library: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = None
    priority: Optional[str] = None


class CuratedExampleUpdateRequest(BaseModel):
    status: Optional[Literal["candidate", "approved", "rejected"]] = None
    use_as_few_shot: Optional[bool] = None
    eval_passed: Optional[bool] = None
    eval_run_id: Optional[int] = None


class ExperimentVariantRequest(BaseModel):
    variant_key: str = Field(min_length=1, max_length=40)
    name: str = Field(default="", max_length=80)
    config: dict = Field(default_factory=dict)
    traffic_pct: int = Field(default=0, ge=0, le=100)
    is_control: bool = False


class ExperimentRequest(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    variants: list[ExperimentVariantRequest] = Field(min_length=1, max_length=10)
    guardrails: dict = Field(default_factory=dict)


class ExperimentUpdateRequest(BaseModel):
    status: Optional[Literal["draft", "running", "paused", "ended"]] = None
    variants: Optional[list[ExperimentVariantRequest]] = None
    guardrails: Optional[dict] = None


class DocRequest(BaseModel):
    path: str
    content: str


class ContentRequest(BaseModel):
    content: str


class SyncRequest(BaseModel):
    source_dir: str


class PermissionReviewRequest(BaseModel):
    status: str


class ProfileRequest(BaseModel):
    display_name: Optional[str] = None
    avatar: Optional[str] = None


def _set_session(response: Response, user_id: int):
    # Cookie 只放随机 token；httponly 防脚本读取，samesite=lax 挡跨站 POST，
    # 生产环境通过 SESSION_SECURE=1 加 Secure 标记。
    response.set_cookie(
        config.SESSION_COOKIE, db.create_session(user_id), httponly=True,
        samesite="lax", max_age=14 * 24 * 60 * 60, secure=config.SESSION_SECURE,
    )


def current_user(request: Request):
    user = db.get_user_by_session(request.cookies.get(config.SESSION_COOKIE))
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def _has_library(user, library):
    return user["role"] == "admin" or db.has_permission(user["id"], library)


def _can_read_library(user, library):
    # 读权限分两层：common 是全员库，任何登录用户可读；
    # 业务库需要审批通过，或者角色是 admin。
    return library == db.COMMON_LIBRARY or _has_library(user, library)


def _require_library(user, library):
    if not _has_library(user, library):
        raise HTTPException(status_code=403, detail=f"你没有“{library}”知识库权限，请先申请并等待管理员审批")


def _require_write_library(user, library):
    # common 是全员共享文档，只有管理员能改，避免普通用户覆盖公共内容。
    # 业务库沿用普通权限判断。
    if library == db.COMMON_LIBRARY and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="全员文档只有管理员可以修改")
    _require_library(user, library)


def _library_name(key):
    for item in db.PERMISSION_CATALOG:
        if item["key"] == key:
            return item["name"]
    return key


@app.get("/")
def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.post("/api/auth/register")
def register(req: AuthRequest, response: Response):
    # 用户名白名单同时挡掉路径分隔符、空格和其他特殊字符；密码长度由 Pydantic 校验。
    username = req.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-\u4e00-\u9fff]{3,40}", username):
        raise HTTPException(status_code=400, detail="用户名需为 3-40 个字的中文、字母、数字、下划线或连字符")
    user = db.create_user(username, req.password)
    if not user:
        raise HTTPException(status_code=409, detail="用户名已存在")
    _set_session(response, user["id"])
    return {"user": user, "quota": db.quota_status(user["id"])}


@app.post("/api/auth/login")
def login(req: AuthRequest, response: Response, request: Request):
    ip = request.client.host if request.client else "unknown"
    key = f"login:{ip}:{req.username.strip().lower()}"
    if rate_limit.blocked(
        key, config.LOGIN_MAX_ATTEMPTS, config.LOGIN_WINDOW_SECONDS
    ):
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    user = db.authenticate(req.username, req.password)
    if not user:
        rate_limit.fail(key, config.LOGIN_WINDOW_SECONDS)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    rate_limit.reset(key)
    _set_session(response, user["id"])
    return {"user": user, "quota": db.quota_status(user["id"])}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    db.delete_session(request.cookies.get(config.SESSION_COOKIE))
    response.delete_cookie(config.SESSION_COOKIE, samesite="lax", secure=config.SESSION_SECURE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return {"user": user, "quota": db.quota_status(user["id"])}


DISPLAY_NAME_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{1,20}")
AVATAR_RE = re.compile(r"data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+")


@app.get("/api/profile")
def api_profile(user=Depends(current_user)):
    profile = db.get_profile(user["id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@app.post("/api/profile")
def api_update_profile(req: ProfileRequest, user=Depends(current_user)):
    # 名称和头像都是可选项，None 表示不修改；头像只接受 300KB 以内的
    # png/jpeg/webp data URL，避免把任意 URL 或超大内容塞进数据库。
    if req.display_name is None and req.avatar is None:
        raise HTTPException(status_code=400, detail="没有要修改的内容")
    display_name = req.display_name
    if display_name is not None:
        display_name = display_name.strip()
        if not DISPLAY_NAME_RE.fullmatch(display_name):
            raise HTTPException(status_code=400, detail="名称只能包含中文和英文字符（1–20 个）")
    if req.avatar is not None and (len(req.avatar) > 400_000 or not AVATAR_RE.fullmatch(req.avatar)):
        raise HTTPException(status_code=400, detail="头像格式不支持或过大，请换一张 300KB 以内的图片")
    ok, error = db.update_profile(user["id"], display_name, req.avatar)
    if not ok:
        raise HTTPException(status_code=429, detail=error)
    return {"ok": True, "profile": db.get_profile(user["id"])}


@app.get("/api/quota")
def quota(user=Depends(current_user)):
    return db.quota_status(user["id"])


@app.get("/api/permissions")
def permissions(user=Depends(current_user)):
    statuses = db.permission_statuses(user["id"])
    return {"catalog": db.list_permissions(), "permissions": statuses, "approved": db.approved_permissions(user["id"]), "is_admin": user["role"] == "admin"}


@app.post("/api/permissions/{permission_key}/request")
def request_permission(permission_key: str, user=Depends(current_user)):
    item = db.request_permission(user["id"], permission_key)
    if item is None:
        raise HTTPException(status_code=404, detail="权限不存在")
    return {"ok": True, "request": item, "permissions": db.permission_statuses(user["id"])}


@app.get("/api/admin/users")
def admin_users(_admin=Depends(admin_user)):
    return {"users": db.list_users()}


@app.get("/api/admin/permission-requests")
def admin_permission_requests(_admin=Depends(admin_user)):
    return {"requests": db.list_permission_requests()}


@app.post("/api/admin/permission-requests/{request_id}")
def review_permission(request_id: int, req: PermissionReviewRequest, admin=Depends(admin_user)):
    result = db.review_permission(request_id, req.status, admin["id"])
    if result is None:
        raise HTTPException(status_code=404, detail="权限申请不存在，或审批状态不合法")
    audit.log(
        admin["id"], "permission.review", "permission_request", request_id,
        {"status": req.status},
    )
    return {"ok": True, "request": result}


@app.post("/api/admin/users/{user_id}/reset-quota")
def admin_reset_quota(user_id: int, admin=Depends(admin_user)):
    users = {user["id"]: user for user in db.list_users()}
    target = users.get(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["role"] == "admin":
        raise HTTPException(status_code=400, detail="管理员没有每日额度，无需重置")
    if not db.reset_quota(user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    audit.log(admin["id"], "user.reset_quota", "user", user_id)
    return {"ok": True, "user": {**target, "quota": db.quota_status(user_id)}}


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: int, admin=Depends(admin_user)):
    result = db.delete_user(user_id, admin["id"])
    messages = {
        "not_found": (404, "用户不存在"),
        "self": (400, "不能删除当前登录的管理员账号"),
        "admin": (400, "不能通过此入口删除管理员账号"),
    }
    if result in messages:
        status, detail = messages[result]
        raise HTTPException(status_code=status, detail=detail)
    audit.log(admin["id"], "user.delete", "user", user_id)
    return {"ok": True, "deleted_user_id": user_id}


@app.get("/api/admin/feedback")
def admin_feedback(
    page: int = 1,
    page_size: int = 20,
    sentiment: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    library: Optional[str] = None,
    grounded: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return db.list_feedback(
        page=page,
        page_size=page_size,
        sentiment=sentiment,
        category=category,
        status=status,
        library=library,
        grounded=grounded,
        date_from=date_from,
        date_to=date_to,
        q=(q or "")[:100] or None,
    )


FEEDBACK_CSV_COLUMNS = (
    ("id", "反馈ID"),
    ("created_at", "提交时间"),
    ("user_id", "用户ID"),
    ("username", "用户"),
    ("question", "问题"),
    ("answer", "回答"),
    ("sentiment", "情感"),
    ("rating", "评分"),
    ("reasons", "原因"),
    ("comment", "评论"),
    ("corrected_answer", "纠正答案"),
    ("status", "状态"),
    ("triage_category", "分流"),
    ("triage_note", "处理备注"),
    ("grounded", "是否grounded"),
    ("refusal_reason", "拒答原因"),
    ("best_rerank_score", "最高重排分"),
    ("libraries", "知识库"),
)


_PII_PATTERNS = (
    (re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"), "[id]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[phone]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
)
_CSV_PII_KEYS = {"question", "answer", "comment", "corrected_answer", "triage_note"}


def _redact_pii(value):
    text = "" if value is None else str(value)
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    # 防止 Excel 把 = + - @ 开头的单元格当成公式执行。
    return "'" + text if text[:1] in {"=", "+", "-", "@"} else text


@app.get("/api/admin/feedback/export.csv")
def admin_feedback_export(
    sentiment: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    library: Optional[str] = None,
    grounded: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    q: Optional[str] = None,
    redact_pii: bool = True,
    _admin=Depends(admin_user),
):
    rows = db.export_feedback(
        sentiment=sentiment,
        category=category,
        status=status,
        library=library,
        grounded=grounded,
        date_from=date_from,
        date_to=date_to,
        q=(q or "")[:100] or None,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([label for _, label in FEEDBACK_CSV_COLUMNS])
    for row in rows:
        cells = []
        for key, _ in FEEDBACK_CSV_COLUMNS:
            value = row.get(key)
            if redact_pii and key == "username":
                value = "[user]"
            elif redact_pii and key in _CSV_PII_KEYS:
                value = _redact_pii(value)
            cells.append(_csv_cell(value))
        writer.writerow(cells)
    audit.log(
        _admin["id"], "feedback.export", "feedback", None,
        {"rows": len(rows), "redact_pii": redact_pii},
    )
    # 带 BOM，Excel 直接打开中文不乱码。
    return Response(
        content=chr(0xFEFF) + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feedback.csv"'},
    )


@app.get("/api/admin/feedback/{feedback_id}")
def admin_feedback_detail(feedback_id: int, _admin=Depends(admin_user)):
    item = db.feedback_detail(feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return {"feedback": item}


@app.patch("/api/admin/feedback/{feedback_id}")
def admin_feedback_triage(
    feedback_id: int, req: FeedbackTriageRequest, admin=Depends(admin_user)
):
    if req.category not in feedback_rules.TRIAGE_CATEGORIES:
        raise HTTPException(status_code=422, detail="未知分流类别")
    item = db.triage_feedback(feedback_id, admin["id"], req.status, req.category, req.note)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    audit.log(
        admin["id"], "feedback.triage", "feedback", feedback_id,
        {"status": req.status, "category": req.category},
    )
    return {"ok": True, "feedback": item}


@app.get("/api/admin/analytics/overview")
def admin_analytics_overview(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return analytics.overview(days)


@app.get("/api/admin/analytics/timeseries")
def admin_analytics_timeseries(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.timeseries(days)}


@app.get("/api/admin/analytics/libraries")
def admin_analytics_libraries(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.libraries(days)}


@app.get("/api/admin/analytics/reasons")
def admin_analytics_reasons(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.reasons(days)}


@app.get("/api/admin/analytics/categories")
def admin_analytics_categories(days: int = analytics.DEFAULT_DAYS, _admin=Depends(admin_user)):
    return {"items": analytics.categories(days)}


@app.get("/api/admin/analytics/clusters")
def admin_analytics_clusters(
    days: int = analytics.DEFAULT_DAYS,
    limit: int = 20,
    _admin=Depends(admin_user),
):
    return {"items": analytics.clusters(days, limit)}


@app.get("/api/admin/content-tasks")
def admin_content_tasks(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    kind: Optional[str] = None,
    library: Optional[str] = None,
    q: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return content_store.list_content_tasks(
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        kind=kind,
        library=library,
        q=(q or "")[:100] or None,
    )


@app.post("/api/admin/content-tasks")
def admin_create_content_task(req: ContentTaskRequest, admin=Depends(admin_user)):
    if req.kind not in content.KINDS:
        raise HTTPException(status_code=422, detail="未知任务类型")
    if req.priority not in content.PRIORITIES:
        raise HTTPException(status_code=422, detail="未知优先级")
    try:
        task = content_store.create_content_task(
            title=req.title,
            description=req.description,
            source=req.source,
            heading=req.heading,
            library=req.library,
            kind=req.kind,
            priority=req.priority,
            owner_id=req.owner_id,
            eval_run_id=req.eval_run_id,
            created_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.log(
        admin["id"], "content_task.create", "content_task", task["id"],
        {"kind": req.kind, "priority": req.priority},
    )
    return {"ok": True, "task": task}


@app.get("/api/admin/content-tasks/{task_id}")
def admin_content_task_detail(task_id: int, _admin=Depends(admin_user)):
    task = content_store.get_content_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="内容任务不存在")
    return {"task": task}


@app.patch("/api/admin/content-tasks/{task_id}")
def admin_update_content_task(
    task_id: int, req: ContentTaskUpdateRequest, admin=Depends(admin_user)
):
    if req.kind is not None and req.kind not in content.KINDS:
        raise HTTPException(status_code=422, detail="未知任务类型")
    try:
        task = content_store.update_content_task(
            task_id,
            status=req.status,
            priority=req.priority,
            kind=req.kind,
            owner_id=req.owner_id,
            resolution_note=req.resolution_note,
            eval_run_id=req.eval_run_id,
            updated_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not task:
        raise HTTPException(status_code=404, detail="内容任务不存在")
    audit.log(
        admin["id"], "content_task.update", "content_task", task_id,
        {"status": req.status, "priority": req.priority, "kind": req.kind},
    )
    return {"ok": True, "task": task}


@app.post("/api/admin/feedback/{feedback_id}/task")
def admin_task_from_feedback(
    feedback_id: int,
    req: Optional[ContentTaskFromFeedbackRequest] = None,
    admin=Depends(admin_user),
):
    try:
        result = content.create_task_for_feedback(
            feedback_id, admin["id"], req.model_dump() if req else {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="反馈不存在")
    audit.log(
        admin["id"], "content_task.from_feedback", "feedback", feedback_id,
        {"task_id": result["task"]["id"], "created": result["created"]},
    )
    return {"ok": True, **result}


@app.get("/api/admin/curated-examples")
def admin_curated_examples(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    library: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return curated_store.list_examples(
        page=page, page_size=page_size, status=status, library=library
    )


@app.get("/api/admin/curated-examples/{example_id}")
def admin_curated_example_detail(example_id: int, _admin=Depends(admin_user)):
    example = curated_store.get_example(example_id)
    if not example:
        raise HTTPException(status_code=404, detail="精选正例不存在")
    return {"example": example}


@app.patch("/api/admin/curated-examples/{example_id}")
def admin_update_curated_example(
    example_id: int, req: CuratedExampleUpdateRequest, admin=Depends(admin_user)
):
    try:
        example = curated_store.update_example(
            example_id,
            status=req.status,
            use_as_few_shot=req.use_as_few_shot,
            eval_passed=req.eval_passed,
            eval_run_id=req.eval_run_id,
            reviewed_by=admin["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not example:
        raise HTTPException(status_code=404, detail="精选正例不存在")
    audit.log(
        admin["id"], "curated.update", "curated_example", example_id,
        {
            "status": req.status,
            "use_as_few_shot": req.use_as_few_shot,
            "eval_passed": req.eval_passed,
        },
    )
    return {"ok": True, "example": example}


@app.get("/api/admin/experiments")
def admin_experiments(_admin=Depends(admin_user)):
    return {"items": experiments.list_experiments()}


@app.post("/api/admin/experiments")
def admin_create_experiment(req: ExperimentRequest, admin=Depends(admin_user)):
    try:
        item = experiments.create_experiment(
            req.key,
            req.name,
            req.description,
            [variant.model_dump() for variant in req.variants],
            req.guardrails,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    audit.log(
        admin["id"], "experiment.create", "experiment", item["key"],
        {"variants": [variant["variant_key"] for variant in item["variants"]]},
    )
    return {"ok": True, "experiment": item}


@app.get("/api/admin/experiments/{key}")
def admin_experiment_detail(key: str, _admin=Depends(admin_user)):
    item = experiments.get_experiment(key)
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    return {"experiment": item}


@app.patch("/api/admin/experiments/{key}")
def admin_update_experiment(
    key: str, req: ExperimentUpdateRequest, admin=Depends(admin_user)
):
    try:
        item = experiments.update_experiment(
            key,
            status=req.status,
            variants=[variant.model_dump() for variant in req.variants]
            if req.variants is not None
            else None,
            guardrails=req.guardrails,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    audit.log(
        admin["id"], "experiment.update", "experiment", key,
        {"status": req.status, "variants": req.variants is not None},
    )
    return {"ok": True, "experiment": item}


@app.get("/api/admin/experiments/{key}/results")
def admin_experiment_results(
    key: str, days: int = 14, _admin=Depends(admin_user)
):
    item = experiments.experiment_results(key, days)
    if not item:
        raise HTTPException(status_code=404, detail="实验不存在")
    return item


@app.get("/api/admin/eval/runs")
def admin_eval_runs(page: int = 1, page_size: int = 20, _admin=Depends(admin_user)):
    return eval_store.list_runs(page=page, page_size=page_size)


@app.get("/api/admin/eval/runs/{run_id}")
def admin_eval_run_detail(run_id: int, _admin=Depends(admin_user)):
    item = eval_store.get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="评测记录不存在")
    return {"run": item}


@app.get("/api/admin/audit-log")
def admin_audit_log(
    page: int = 1,
    page_size: int = 20,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    _admin=Depends(admin_user),
):
    return audit.list_events(
        page=page,
        page_size=page_size,
        action=action,
        target_type=target_type,
        actor_id=actor_id,
        date_from=date_from,
        date_to=date_to,
    )


def _ask_error_detail(exc):
    # 把上游异常翻译成可行动的中文，避免 SDK 堆栈或 Key 泄露到前端。
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, AuthenticationError):
        return "大模型服务认证失败：请检查 .env 中的 DEEPSEEK_API_KEY 是否有效（当前 Key 被服务端拒绝）。"
    if isinstance(exc, RateLimitError):
        return "大模型服务限流或余额不足，请稍后重试或检查账户额度。"
    if isinstance(exc, APIConnectionError):
        return "无法连接大模型服务（网络或代理问题），请检查 DEEPSEEK_BASE_URL 与网络连通性。"
    if isinstance(exc, APIStatusError):
        return f"大模型服务返回异常状态 {exc.status_code}：{str(exc)[:200]}"
    return f"问答处理失败（{type(exc).__name__}）：{str(exc)[:200]}"


def _raise_ask_error(exc):
    # 状态码按“客户端可修复 / 上游故障”分开：404/400 是输入、配置或对话不存在，
    # 502/503/504 是上游认证、限流或连接问题，其余按 500 兜底。
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=404, detail=_ask_error_detail(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=400, detail=_ask_error_detail(exc))
    if isinstance(exc, AuthenticationError):
        raise HTTPException(status_code=502, detail=_ask_error_detail(exc))
    if isinstance(exc, RateLimitError):
        raise HTTPException(status_code=503, detail=_ask_error_detail(exc))
    if isinstance(exc, APIConnectionError):
        raise HTTPException(status_code=504, detail=_ask_error_detail(exc))
    if isinstance(exc, APIStatusError):
        raise HTTPException(status_code=502, detail=_ask_error_detail(exc))
    raise HTTPException(status_code=500, detail=_ask_error_detail(exc))


def _sse(payload, event=None):
    # SSE 事件以空行结束；data 只放单行 JSON，前端按 \n\n 切包。
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(payload, ensure_ascii=False))
    return "\n".join(lines) + "\n\n"


@app.post("/api/ask")
def api_ask(req: AskRequest, user=Depends(current_user)):
    """问答入口，返回 JSON 或 SSE。

    顺序是刻意的：
    0) 先做只读的额度预检查，超限直接 429，不进入检索；
    1) 再 prepare：完成授权、检索、证据判断。拒答直接作为普通 JSON 返回，
       不进入生成阶段，也不扣次数；若开启查询改写，检索阶段仍可能调用一次
       模型做改写，但不会生成回答；
    2) 只有确认可以生成时才创建事件流，逐 token 推给页面；
    3) 生成结束后才 consume_quota，避免模型报错把次数吃掉。
    """
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    # 没有已审批业务库时仍可检索全员文档；拒答不扣次数。有业务库时，只有生成成功才扣次数。
    business = db.business_permissions(user["id"])
    status = db.quota_status(user["id"])
    if business and not status.get("unlimited") and (status.get("remaining") or 0) <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"今日咨询次数已用完（每天最多 {config.DAILY_ASK_LIMIT} 次），请明天再来。",
            headers={"Retry-After": "3600"},
        )
    if req.conversation_id is not None and not db.conversation_for_user(user["id"], req.conversation_id):
        raise HTTPException(status_code=404, detail="找不到这组对话")
    try:
        prepared = rag.prepare(question, user["id"], req.conversation_id)
    except Exception as exc:
        _raise_ask_error(exc)

    if not prepared.get("ready"):
        prepared["quota"] = db.quota_status(user["id"])
        return prepared

    # 到这里检索和拒答都已结束。下面只把有依据的回答逐段推给页面，流结束后才扣次数。
    def events():
        parts = []
        started = time.perf_counter()
        try:
            for token in llm.generate_stream(rag.SYSTEM_PROMPT, prepared["user_prompt"]):
                parts.append(token)
                yield _sse({"token": token}, event="token")
            generation_ms = int((time.perf_counter() - started) * 1000)
            result = rag.persist_prepared(prepared, "".join(parts), generation_ms=generation_ms)
            if business:
                result["quota"] = db.consume_quota(user["id"]) or db.quota_status(user["id"])
            else:
                result["quota"] = db.quota_status(user["id"])
            yield _sse(result, event="done")
        except Exception as exc:
            yield _sse({"detail": _ask_error_detail(exc)}, event="error")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/source-click")
def source_click(req: SourceClickRequest, user=Depends(current_user)):
    answer = db.answer_for_user(req.answer_id, user["id"])
    if not answer:
        raise HTTPException(status_code=404, detail="找不到这条回答")
    db.record_source_click(
        req.answer_id,
        user["id"],
        req.source,
        heading=req.heading,
        anchor=req.anchor,
        library=req.library,
        source_index=req.source_index,
    )
    return {"ok": True}


@app.post("/api/feedback")
def feedback(req: FeedbackRequest, user=Depends(current_user)):
    answer = db.answer_for_user(req.answer_id, user["id"])
    if not answer:
        raise HTTPException(status_code=404, detail="找不到这条回答")
    sources = _sources_from_json(answer["sources_json"])
    try:
        normalized = feedback_rules.normalize(req.model_dump(), sources)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        feedback_id = db.save_feedback(
            req.answer_id,
            user["id"],
            sentiment=normalized["sentiment"],
            reasons=normalized["reasons"],
            comment=normalized["comment"],
            corrected_answer=normalized["corrected_answer"],
            source_marks=normalized["source_marks"],
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="这条回答已经评价过了")
    if feedback_id is None:
        raise HTTPException(status_code=404, detail="找不到这条回答")
    trace = tracing.get_trace_by_answer(req.answer_id)
    category, confidence, note = feedback_rules.classify(normalized, trace)
    db.set_feedback_triage(feedback_id, category, confidence, note)
    if normalized["sentiment"] == "positive":
        try:
            curated_store.ensure_candidate(req.answer_id, feedback_id)
        except Exception:  # 精选失败不能影响反馈本身
            logger.exception("ensure curated example failed")
    return {"ok": True, "feedback": db.get_feedback(feedback_id, user["id"])}


@app.patch("/api/feedback/{feedback_id}")
def update_feedback(feedback_id: int, req: FeedbackUpdateRequest, user=Depends(current_user)):
    current = db.get_feedback(feedback_id, user["id"])
    if not current:
        raise HTTPException(status_code=404, detail="找不到这条反馈")
    created = datetime.fromisoformat(current["created_at"])
    if datetime.now(timezone.utc) - created > timedelta(hours=config.FEEDBACK_EDIT_WINDOW_HOURS):
        raise HTTPException(status_code=403, detail="反馈已超过可修改时间")
    answer = db.answer_for_user(current["answer_id"], user["id"])
    if not answer:
        raise HTTPException(status_code=404, detail="找不到这条回答")
    sources = _sources_from_json(answer["sources_json"])
    payload = req.model_dump()
    sentiment = payload.get("sentiment") or current["sentiment"]
    merged = {
        "sentiment": sentiment,
        "reasons": payload.get("reasons") if payload.get("reasons") is not None else current["reasons"],
        "comment": payload.get("comment") if payload.get("comment") is not None else current["comment"],
        "corrected_answer": (
            payload.get("corrected_answer")
            if payload.get("corrected_answer") is not None
            else current["corrected_answer"]
        ),
        "source_marks": (
            payload.get("source_marks")
            if payload.get("source_marks") is not None
            else current["source_marks"]
        ),
    }
    try:
        normalized = feedback_rules.normalize(merged, sources)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = db.update_feedback(
        feedback_id,
        user["id"],
        sentiment=normalized["sentiment"],
        reasons=normalized["reasons"],
        comment=normalized["comment"],
        corrected_answer=normalized["corrected_answer"],
        source_marks=normalized["source_marks"],
    )
    trace = tracing.get_trace_by_answer(current["answer_id"])
    category, confidence, note = feedback_rules.classify(normalized, trace)
    db.set_feedback_triage(feedback_id, category, confidence, note)
    try:
        if normalized["sentiment"] == "positive":
            curated_store.ensure_candidate(current["answer_id"], feedback_id)
        else:
            curated_store.invalidate_candidate(current["answer_id"])
    except Exception:  # 精选状态同步失败不能影响反馈修改
        logger.exception("sync curated example failed")
    return {"ok": True, "feedback": updated}


@app.get("/api/feedback/answer/{answer_id}")
def get_answer_feedback(answer_id: int, user=Depends(current_user)):
    answer = db.answer_for_user(answer_id, user["id"])
    if not answer:
        raise HTTPException(status_code=404, detail="找不到这条回答")
    return {"feedback": db.get_feedback_by_answer(answer_id, user["id"])}


def _sources_from_json(raw):
    try:
        sources = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return sources if isinstance(sources, list) else []


def _feedback_reasons(raw):
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _message_feedback(row):
    if row["feedback_id"] is None:
        return None
    return {
        "id": row["feedback_id"],
        "rating": row["rating"],
        "sentiment": row["sentiment"],
        "reasons": _feedback_reasons(row["reasons_json"]),
        "comment": row["comment"],
        "corrected_answer": row["corrected_answer"],
        "status": row["status"],
    }


@app.get("/api/conversations")
def api_conversations(user=Depends(current_user)):
    return {"conversations": db.list_conversations(user["id"])}


@app.get("/api/conversations/{conversation_id}")
def api_conversation(conversation_id: int, user=Depends(current_user)):
    found = db.conversation_messages(user["id"], conversation_id)
    if not found:
        raise HTTPException(status_code=404, detail="找不到这组对话")
    convo, rows = found
    return {
        "id": convo["id"],
        "title": convo["title"],
        "updated_at": convo["updated_at"],
        "messages": [
            {
                "answer_id": row["id"],
                "question": row["question"],
                "answer_html": md_render.render(row["answer"] or ""),
                "sources": _sources_from_json(row["sources_json"]),
                "created_at": row["created_at"],
                "rating": row["rating"],
                "feedback": _message_feedback(row),
            }
            for row in rows
        ],
    }


@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: int, user=Depends(current_user)):
    if not db.delete_conversation(user["id"], conversation_id):
        raise HTTPException(status_code=404, detail="找不到这组对话")
    return {"ok": True}


def _doc_tree(user):
    # 按权限裁剪文档树；一个目录下没有可见文件时整枝隐藏，
    # 避免通过目录名推测知识库结构。
    docs_dir = Path(config.DOCS_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)

    def walk(dirpath):
        dirs, files = [], []
        for entry in sorted(dirpath.iterdir()):
            if entry.is_dir():
                child = walk(entry)
                if child["dirs"] or child["files"]:
                    dirs.append(child)
            elif documents.is_supported(entry.suffix):
                path = entry.relative_to(docs_dir).as_posix()
                library = ingest.library_for_source(path)
                if _can_read_library(user, library):
                    files.append({"path": path, "name": entry.name, "library": library})
        return {"name": dirpath.name, "dirs": dirs, "files": files}

    return walk(docs_dir)


@app.get("/api/docs")
def api_docs(user=Depends(current_user)):
    return {"tree": _doc_tree(user), "libraries": db.permission_statuses(user["id"]), "approved": db.approved_permissions(user["id"])}


@app.get("/api/doc/{path:path}")
def api_doc(path: str, user=Depends(current_user)):
    # 检查顺序：路径必须留在 docs/ 内，然后确认文件存在且后缀受支持，最后查读权限。
    # 不存在返回 404、无权限返回 403，因此调用方能区分文件是否存在；
    # 若要避免泄露存在性，应先按路径判断知识库读权限。
    # 返回提取后的文本和渲染 HTML，不把原始二进制直接交给浏览器。
    docs_dir = Path(config.DOCS_DIR).resolve()
    full = (docs_dir / path).resolve()
    if not full.is_relative_to(docs_dir) or not full.exists() or not documents.is_supported(full.suffix):
        raise HTTPException(status_code=404, detail="文档不存在")
    if not _can_read_library(user, ingest.library_for_source(path)):
        raise HTTPException(status_code=403, detail="你没有该文档的阅读权限")
    try:
        content = documents.extract_bytes(full.name, full.read_bytes())
    except documents.ExtractError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "path": path,
        "library": ingest.library_for_source(path),
        "content": content,
        "html": md_render.render(content),
        "editable": documents.is_editable(full.suffix),
    }


def _resolve_doc(path):
    docs_dir = Path(config.DOCS_DIR).resolve()
    full = (docs_dir / path).resolve()
    if not full.is_relative_to(docs_dir):
        raise HTTPException(status_code=400, detail="非法路径")
    if not documents.is_supported(full.suffix):
        raise HTTPException(status_code=400, detail="不支持该文档格式")
    return full


@app.post("/api/doc")
def create_doc(req: DocRequest, user=Depends(current_user)):
    # 在线新建只产生 Markdown。先判断“目录存在但无权限”，再判断“文档已存在”，
    # 避免对无权限用户返回 409，从而泄露具体文件名是否已被占用。
    path = req.path.strip().strip("/")
    if not path:
        raise HTTPException(status_code=400, detail="路径不能为空")
    if not path.lower().endswith(".md"):
        path += ".md"
    library = ingest.library_for_source(path)
    full = _resolve_doc(path)
    # 目录（或同名文档）在文件系统里已存在，但当前用户无该库权限 → 明确提示“已存在，请申请权限”
    if (full.parent.exists() or full.exists()) and not _can_read_library(user, library):
        raise HTTPException(
            status_code=403,
            detail=f"该目录已存在，但你没有「{_library_name(library)}」知识库的访问权限，请先申请权限",
        )
    _require_write_library(user, library)
    if full.exists():
        raise HTTPException(status_code=409, detail="文档已存在")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(req.content, encoding="utf-8")
    chunks = ingest.ingest_one(path, req.content)
    return {"path": path, "library": library, "chunks": chunks}


@app.put("/api/doc/{path:path}")
def update_doc(path: str, req: ContentRequest, _admin=Depends(admin_user)):
    full = _resolve_doc(path)
    if not full.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    if not documents.is_editable(full.suffix):
        raise HTTPException(status_code=400, detail="该格式不能在线编辑，请重新上传文件")
    full.write_text(req.content, encoding="utf-8")
    chunks = ingest.ingest_one(path, req.content)
    return {"path": path, "chunks": chunks}


@app.delete("/api/doc/{path:path}")
def delete_doc(path: str, _admin=Depends(admin_user)):
    full = _resolve_doc(path)
    if not full.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    full.unlink()
    ingest.delete_source(path)
    return {"ok": True}


@app.post("/api/upload")
async def upload_docs(files: list[UploadFile] = File(...), dir: str = Form(""), user=Depends(current_user)):
    # 上传有三道边界：
    # 1) 文件名只取 basename，丢掉客户端可能带上的目录；
    # 2) 目标目录 resolve 后必须仍在 docs/ 内，防 ../ 穿越；
    # 3) 落盘保存原始字节作为源文件，入库使用提取出的文本（当前没有原始文件下载接口）。
    # 普通用户只能新建、不能覆盖；管理员可以覆盖同名文件。
    docs_dir = Path(config.DOCS_DIR).resolve()
    target_dir = docs_dir
    if dir.strip():
        target_dir = (docs_dir / dir.strip().strip("/")).resolve()
        if not target_dir.is_relative_to(docs_dir):
            raise HTTPException(status_code=400, detail="非法目录")
    target_dir.mkdir(parents=True, exist_ok=True)

    uploaded = []
    skipped = []
    for f in files:
        name = Path(f.filename or "").name
        if not name or name in {".", ".."}:
            skipped.append({"name": name or "未命名文件", "reason": "文件名无效"})
            continue
        raw = await f.read()
        try:
            text = documents.extract_bytes(name, raw)
        except documents.ExtractError as exc:
            skipped.append({"name": name, "reason": str(exc)})
            continue
        dest = target_dir / name
        rel = dest.relative_to(docs_dir).as_posix()
        _require_write_library(user, ingest.library_for_source(rel))
        if dest.exists() and user["role"] != "admin":
            raise HTTPException(status_code=409, detail="普通用户只能创建新文档，不能覆盖已有文档")
        dest.write_bytes(raw)
        chunks = await run_in_threadpool(ingest.ingest_one, rel, text)
        uploaded.append({"path": rel, "library": ingest.library_for_source(rel), "chunks": chunks})
    return {"uploaded": uploaded, "skipped": skipped}


@app.post("/api/sync")
def sync_dir(req: SyncRequest, _admin=Depends(admin_user)):
    # 复制并立即索引，源目录不受影响。提取失败或路径非法的文件记入 skipped；
    # 其他 I/O 或索引异常会直接中断本次同步。
    source = Path(req.source_dir.strip()).resolve()
    if not source.exists() or not source.is_dir():
        raise HTTPException(status_code=400, detail="源目录不存在")
    docs_dir = Path(config.DOCS_DIR)
    synced = []
    skipped = []
    for f in documents.iter_files(source):
        rel = f.relative_to(source)
        try:
            raw = f.read_bytes()
            text = documents.extract_bytes(f.name, raw)
        except documents.ExtractError as exc:
            skipped.append({"name": rel.as_posix(), "reason": str(exc)})
            continue
        dest = (Path(docs_dir) / rel).resolve()
        if not dest.is_relative_to(Path(docs_dir).resolve()):
            skipped.append({"name": rel.as_posix(), "reason": "非法路径"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        rel_path = dest.relative_to(docs_dir).as_posix()
        ingest.ingest_one(rel_path, text)
        synced.append(rel_path)
    return {"count": len(synced), "synced": synced, "skipped": skipped}


@app.post("/api/ingest")
def api_ingest(_admin=Depends(admin_user)):
    return ingest.run_ingest()
