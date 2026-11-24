"""反馈枚举、校验与规则分流。

这里不调用大模型：反馈入库只做格式校验和规则归因，LLM 相关的离线分析
放在脚本里，避免用户点一次反馈就产生一次模型调用。
"""

FEEDBACK_REASONS = {
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
POSITIVE_REASONS = {"helpful", "accurate", "complete", "well_cited"}
SOURCE_MARKS = {"wrong_citation", "irrelevant", "outdated", "missing_context"}
TRIAGE_STATUSES = {"new", "triaged", "in_progress", "resolved", "dismissed"}
TRIAGE_CATEGORIES = {
    "positive",
    "retrieval_failure",
    "generation_failure",
    "citation_issue",
    "doc_issue",
    "permission",
    "ux",
    "unknown",
}


def sentiment_from_rating(rating):
    return "positive" if int(rating) >= 5 else "negative"


def normalize(payload, sources):
    """把新旧两套反馈字段归一化。校验失败抛 ValueError，由 HTTP 层映射成 422。"""
    rating = payload.get("rating")
    sentiment = payload.get("sentiment")
    if sentiment is None:
        if rating is None:
            raise ValueError("缺少 sentiment 或 rating")
        sentiment = sentiment_from_rating(rating)
    if sentiment not in {"positive", "negative"}:
        raise ValueError("sentiment 只能是 positive 或 negative")
    if rating is not None and sentiment_from_rating(rating) != sentiment:
        raise ValueError("sentiment 与 rating 不一致")

    reasons = [str(item) for item in (payload.get("reasons") or []) if str(item)]
    allowed = set(FEEDBACK_REASONS) | POSITIVE_REASONS
    unknown = [item for item in reasons if item not in allowed]
    if unknown:
        raise ValueError(f"未知反馈原因：{', '.join(unknown)}")
    # 点赞和点踩的原因集合不同。切换到另一侧时丢掉不属于当前情感的原因，
    # 避免把旧的 helpful 带进点踩，或把点踩原因写进点赞。
    if sentiment == "negative":
        reasons = [item for item in reasons if item in FEEDBACK_REASONS]
    else:
        reasons = [item for item in reasons if item in POSITIVE_REASONS]

    comment = (payload.get("comment") or payload.get("reason") or "").strip()
    # 兼容旧前端：只传 rating + 自由文本原因时，把原因归到“其他”。
    if sentiment == "negative" and not reasons and len(comment) >= 10:
        reasons = ["other"]
    if sentiment == "negative" and not reasons:
        raise ValueError("点踩时至少选择一个原因")
    if "other" in reasons and len(comment) < 10:
        raise ValueError("选择“其他”时请补充至少 10 个字符的说明")
    if sentiment == "positive" and not reasons:
        reasons = ["helpful"]

    marks = []
    seen = set()
    for mark in payload.get("source_marks") or []:
        index = int(mark.get("source_index") or 0)
        if index < 1 or index > len(sources):
            raise ValueError("引用标记超出了本次回答的来源范围")
        kind = mark.get("mark")
        if kind not in SOURCE_MARKS:
            raise ValueError(f"未知引用标记：{kind}")
        key = (index, kind)
        if key not in seen:
            seen.add(key)
            marks.append({"source_index": index, "mark": kind})

    corrected = (payload.get("corrected_answer") or "").strip()
    if len(corrected) > 4000:
        raise ValueError("纠正答案不能超过 4000 个字符")

    return {
        "sentiment": sentiment,
        "rating": int(rating) if rating is not None else (5 if sentiment == "positive" else 1),
        "reasons": reasons,
        "comment": comment,
        "corrected_answer": corrected,
        "source_marks": marks,
    }


def classify(feedback, trace=None):
    """只根据反馈原因和检索轨迹做规则分流，返回 (category, confidence, note)。"""
    reasons = set(feedback.get("reasons") or [])
    marks = {mark.get("mark") for mark in (feedback.get("source_marks") or [])}
    if feedback.get("sentiment") == "positive":
        return "positive", 0.9, "正向反馈"
    if "permission" in reasons:
        return "permission", 0.9, "用户反馈权限或范围问题"
    if "outdated" in reasons or "outdated" in marks:
        return "doc_issue", 0.9, "资料过时"
    if "citation_wrong" in reasons or "wrong_citation" in marks:
        return "citation_issue", 0.9, "引用不正确"
    if "irrelevant" in marks:
        return "retrieval_failure", 0.8, "标记的来源不相关"
    if "missing_context" in marks:
        return "retrieval_failure", 0.7, "标记的来源缺少上下文"
    if "retrieval_miss" in reasons:
        return "retrieval_failure", 0.9, "用户反馈没找到相关资料"
    if "unjustified_refusal" in reasons:
        return "retrieval_failure", 0.8, "本应回答却拒答"
    if "formatting" in reasons:
        return "ux", 0.9, "格式或表达问题"

    trace = trace or {}
    grounded = bool(trace.get("grounded"))
    best_rerank = trace.get("best_rerank_score")
    if reasons & {"wrong_info", "incomplete"}:
        if not grounded:
            return "retrieval_failure", 0.6, "回答未 grounding，优先排查检索"
        if best_rerank is not None and float(best_rerank) >= 0.5:
            return "generation_failure", 0.6, "已检索到较相关片段，优先排查生成"
        return "unknown", 0.3, "证据不足，需人工复核"
    return "unknown", 0.3, "未匹配到明确规则"
