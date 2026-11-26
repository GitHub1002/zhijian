"""请求级可观测性：request_id、耗时和结构化访问日志。

日志只记录方法、路径、状态码和耗时，不记录问题、回答、评论或请求体，
避免把知识库正文和用户输入写进日志。
"""
import json
import logging
import time
import uuid
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

REQUEST_ID = ContextVar("request_id", default="")
logger = logging.getLogger("app.request")
logger.setLevel(logging.INFO)


def setup_logging():
    """配置可选的轮转文件日志；LOG_FILE 留空时只输出 stdout。"""
    if not config.LOG_FILE:
        return
    target = Path(config.LOG_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    resolved = str(target.resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == resolved:
            return
    handler = RotatingFileHandler(
        target,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def new_request_id():
    return uuid.uuid4().hex[:16]


def current_request_id():
    return REQUEST_ID.get()


async def middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = REQUEST_ID.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/static/"):
            # 本地应用没有构建版本号，强制浏览器每次回源校验，避免旧 JS 卡住页面。
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if not request.url.path.startswith("/static/"):
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status,
                        "duration_ms": elapsed_ms,
                    },
                    ensure_ascii=False,
                )
            )
        REQUEST_ID.reset(token)
