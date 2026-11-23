"""内容任务：把负反馈转成可执行的文档修复任务。

规则只做归因和文案整理，不调用模型。同一来源 + 标题 + 任务类型已有未关闭
任务时，把新反馈挂到现有任务上，避免管理端出现大量重复项。
"""
from . import content_store, db

KINDS = {
    "doc_fix": "文档修正",
    "doc_update": "文档更新",
    "doc_missing": "文档缺失",
    "citation_fix": "引用修正",
    "retrieval_gap": "检索缺口",
    "other": "其他",
}
PRIORITIES = {"low", "medium", "high"}
STATUSES = {"open", "in_progress", "resolved", "dismissed"}
REASON_LABELS = {
    "retrieval_miss": "没找到相关资料",
    "wrong_info": "回答内容错误",
    "incomplete": "回答不完整",
    "outdated": "资料过时",
    "citation_wrong": "引用不正确",
    "permission": "权限或范围问题",
    "formatting": "格式或表达问题",
    "unjustified_refusal": "本应回答却拒答",
    "other": "其他",
}


def _library_for(source, feedback):
    trace = feedback.get("trace") or {}
    for candidate in trace.get("candidates") or []:
        if candidate.get("source") == source and candidate.get("library"):
            return candidate["library"]
    for item in feedback.get("sources") or []:
        if isinstance(item, dict) and item.get("source") == source:
            return item.get("library", "")
    return ""


def _target(feedback):
    for mark in feedback.get("source_marks") or []:
        if mark.get("source"):
            return (
                mark["source"],
                mark.get("heading", ""),
                _library_for(mark["source"], feedback),
            )
    trace = feedback.get("trace") or {}
    for candidate in trace.get("candidates") or []:
        if candidate.get("selected") and candidate.get("source"):
            return (
                candidate["source"],
                candidate.get("heading", ""),
                candidate.get("library", ""),
            )
    for source in feedback.get("sources") or []:
        if isinstance(source, dict) and source.get("source"):
            return (
                source["source"],
                source.get("heading", ""),
                source.get("library", ""),
            )
    return "", "", ""


def _kind(feedback, source):
    reasons = set(feedback.get("reasons") or [])
    marks = {mark.get("mark") for mark in (feedback.get("source_marks") or [])}
    if "outdated" in reasons or "outdated" in marks:
        return "doc_update"
    if "citation_wrong" in reasons or "wrong_citation" in marks:
        return "citation_fix"
    if "retrieval_miss" in reasons:
        return "doc_missing" if not source else "retrieval_gap"
    if "unjustified_refusal" in reasons:
        return "retrieval_gap"
    if reasons & {"wrong_info", "incomplete"} or "missing_context" in marks:
        return "doc_fix"
    return "other"


def _priority(feedback):
    reasons = set(feedback.get("reasons") or [])
    marks = {mark.get("mark") for mark in (feedback.get("source_marks") or [])}
    if reasons & {"wrong_info", "outdated", "citation_wrong"} or marks & {
        "outdated", "wrong_citation"
    }:
        return "high"
    if reasons & {"incomplete", "retrieval_miss", "unjustified_refusal"}:
        return "medium"
    return "low"


def build_task(feedback):
    source, heading, library = _target(feedback)
    question = (feedback.get("question") or "").strip()
    reasons = feedback.get("reasons") or []
    comment = (feedback.get("comment") or "").strip()
    corrected = (feedback.get("corrected_answer") or "").strip()
    kind = _kind(feedback, source)

    label = f"{source} > {heading}" if heading else source
    title = label or question[:60] or "未归类反馈"
    if len(title) > 120:
        title = title[:119] + "…"

    lines = [
        f"问题：{question or '（无）'}",
        "用户原因：" + ("、".join(REASON_LABELS.get(item, item) for item in reasons) or "未分类"),
    ]
    if comment:
        lines.append(f"评论：{comment}")
    if corrected:
        lines.append(f"纠正答案：{corrected}")
    trace = feedback.get("trace") or {}
    if trace:
        lines.append(
            "检索：grounded={} best_rerank={} 拒答={}".format(
                trace.get("grounded"),
                trace.get("best_rerank_score"),
                trace.get("refusal_reason") or "无",
            )
        )

    return {
        "title": title,
        "description": "\n".join(lines)[:4000],
        "source": source,
        "heading": heading,
        "library": library,
        "kind": kind,
        "priority": _priority(feedback),
    }


def create_task_for_feedback(feedback_id, actor_id, overrides=None):
    """返回 {task, created}；反馈不存在返回 None；重复调用不会建重复任务。"""
    feedback = db.feedback_detail(feedback_id)
    if not feedback:
        return None
    if feedback.get("sentiment") == "positive":
        raise ValueError("正向反馈不需要创建内容任务")

    existing = content_store.find_linked_content_task(feedback_id)
    if existing:
        return {"task": existing, "created": False}

    payload = build_task(feedback)
    for key in ("title", "description", "source", "heading", "library", "kind", "priority"):
        value = (overrides or {}).get(key)
        if value:
            payload[key] = value

    if payload["kind"] not in KINDS:
        raise ValueError(f"未知任务类型：{payload['kind']}")
    if payload["priority"] not in PRIORITIES:
        raise ValueError(f"未知优先级：{payload['priority']}")

    # 同一文档的同一类问题合并到一个未关闭任务里。
    existing = content_store.find_open_content_task(
        payload["source"], payload["heading"], payload["kind"]
    )
    if existing:
        content_store.link_content_task_feedback(existing["id"], feedback_id)
        return {"task": content_store.get_content_task(existing["id"]), "created": False}

    task = content_store.create_content_task(
        **payload, created_by=actor_id, feedback_id=feedback_id
    )
    return {"task": task, "created": True}
