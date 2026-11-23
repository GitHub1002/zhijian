"""问答先检索、再判断有没有依据，通过之后才调用大模型。

向量检索和 BM25 用倒数排名融合，再用重排模型留下前几段。
查询改写由 RAG_QUERY_REWRITE_LIMIT 控制，默认关闭。
"""
import json
import re
import time

from . import config, curated_store, db, embedder, llm, md_render, store, tracing

# 提示词是行为约束的一部分：只允许引用给定编号，证据不足必须拒答。
# 修改时要同步 README 里的“反幻觉”说明。
SYSTEM_PROMPT = (
    "你是一个企业内部知识库助手。只能使用参考资料回答，不能使用常识补充或猜测。"
    "如果参考资料不足以回答问题，必须直接回复‘当前授权知识库没有足够依据，暂不作答，请申请对应知识库权限或联系管理员。’。"
    "有依据时先给结论，再列必要步骤和例外。关键结论必须使用 [1]、[2] 这样的引用编号；引用编号必须对应参考资料编号。"
    "不要编造来源，不要引用未提供的资料，控制在 480 字以内。"
)

_RERANKER = None


def _get_reranker():
    # 重排模型较大，首次使用时懒加载；加载失败记为 False，后续请求直接走词面兜底。
    global _RERANKER
    if _RERANKER is not None or not config.RERANK_ENABLED:
        return _RERANKER
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _RERANKER = TextCrossEncoder(model_name=config.RERANK_MODEL, lazy_load=True)
    except Exception:
        _RERANKER = False
    return _RERANKER


def _lexical_score(question, text):
    # 中文按二元组、英文数字按整词算重合率；只用于证据判断和重排兜底，不是 BM25 分数。
    def terms(value):
        value = value.lower()
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", value))
        bigrams = {cjk[i:i + 2] for i in range(max(0, len(cjk) - 1))}
        words = set(re.findall(r"[a-z0-9_]+", value))
        return bigrams | words
    question_terms = terms(question)
    text_terms = terms(text)
    if not question_terms:
        return 0.0
    return len(question_terms & text_terms) / len(question_terms)


def _rerank(question, candidates):
    if not candidates:
        return []
    reranker = _get_reranker()
    mode = "lexical"
    if reranker:
        try:
            scores = list(reranker.rerank(question, [item["text"] for item in candidates]))
            for item, score in zip(candidates, scores):
                item["rerank_score"] = float(score)
            mode = "model"
        except Exception:
            reranker = False
    if not reranker:
        # 兜底分 = 词面重合 + RRF，与模型分不可跨批比较；这里只用于同一批候选内部排序。
        for item in candidates:
            item["rerank_score"] = _lexical_score(question, item["text"]) + item.get("rrf_score", 0.0)
    for item in candidates:
        item["rerank_mode"] = mode
    ordered = sorted(candidates, key=lambda item: item.get("rerank_score", 0), reverse=True)
    for rank, item in enumerate(ordered, start=1):
        item["rerank_rank"] = rank
    return ordered


def _hybrid_search(question, libraries):
    # 两路各自取前若干名，再按名次加分。RRF_K 越大，第一名和后面几名的差距越小。
    try:
        qvec = embedder.embed_query(question)
        vector_hits = store.search(qvec, config.HYBRID_TOP_K, libraries)
    except Exception:
        # 向量模型首次下载失败时仍保留 BM25 可用，避免整个知识库无法问答。
        vector_hits = []
    bm25_hits = db.search_bm25(question, libraries, config.HYBRID_TOP_K)
    candidates = {}
    for rank, point in enumerate(vector_hits, start=1):
        payload = dict(point.payload or {})
        chunk_id = str(point.id)
        candidates.setdefault(chunk_id, {
            "chunk_id": chunk_id, "source": payload.get("source", ""), "title": payload.get("title", ""),
            "heading": payload.get("heading", ""), "text": payload.get("text", ""), "library": payload.get("library", ""),
            "vector_score": float(point.score), "bm25_score": None, "rrf_score": 0.0,
        })
        candidates[chunk_id]["vector_score"] = float(point.score)
        candidates[chunk_id]["vector_rank"] = rank
        candidates[chunk_id]["rrf_score"] += 1 / (config.RRF_K + rank)
    for rank, row in enumerate(bm25_hits, start=1):
        item = candidates.setdefault(row["chunk_id"], {
            "chunk_id": row["chunk_id"], "source": row["source"], "title": row["title"],
            "heading": row["heading"], "text": row["text"], "library": row["library"],
            "vector_score": None, "bm25_score": None, "rrf_score": 0.0,
        })
        item["bm25_score"] = float(row["bm25_score"])
        item["bm25_rank"] = rank
        item["rrf_score"] += 1 / (config.RRF_K + rank)
    ranked = sorted(candidates.values(), key=lambda item: item["rrf_score"], reverse=True)
    for rank, item in enumerate(ranked, start=1):
        item["rrf_rank"] = rank
    return _rerank(question, ranked[: max(config.HYBRID_TOP_K, config.RERANK_TOP_K * 3)])


def _source_label(item):
    return f"{item['source']}" + (f" > {item['heading']}" if item.get("heading") else "")


def _rounded(value):
    return round(float(value), 4) if value is not None else None


def _source_dict(index, item):
    last = item.get("heading", "").split(" > ")[-1] if item.get("heading") else ""
    # anchor 取标题路径的最后一段，并复用 md_render.slugify。
    # 前端按这个 id 在重新渲染的文档里找标题，必须和 toc 扩展的 slugify 一致。
    anchor = md_render.slugify(last) if last else ""
    rerank_score = item.get("rerank_score")
    return {
        "index": index,
        "source": item["source"],
        "heading": item.get("heading", ""),
        "anchor": anchor,
        "library": item.get("library", ""),
        "chunk_id": item.get("chunk_id", ""),
        "score": round(float(rerank_score), 4) if rerank_score is not None else 0.0,
        "rerank_score": _rounded(rerank_score),
        "vector_score": round(float(item.get("vector_score") or 0), 4),
        "bm25_score": _rounded(item.get("bm25_score")),
        "rrf_score": _rounded(item.get("rrf_score")),
    }


def _prepare_ms(state):
    started = state.get("started_at")
    return int((time.perf_counter() - started) * 1000) if started else None


def _timings(state):
    value = _prepare_ms(state)
    return {"prepare_ms": value} if value is not None else {}


def _trace_queries(state):
    original = state.get("question") or ""
    rewritten = state.get("retrieval_query") or ""
    queries = [original]
    if rewritten and rewritten != original:
        queries.append(rewritten)
    return queries


def _record_trace(state, answer_id, grounded, refusal_reason="", timings=None):
    conversation_id = (
        db.conversation_id_for_answer(answer_id) if answer_id else state.get("conversation_id")
    )
    return tracing.record_safely(
        answer_id=answer_id,
        user_id=state.get("user_id"),
        conversation_id=conversation_id,
        question=state.get("question", ""),
        queries=_trace_queries(state),
        retrieval_query=state.get("retrieval_query") or state.get("question", ""),
        query_rewrites=state.get("rewrite_count", 0),
        libraries=state.get("libraries", []),
        grounded=grounded,
        refusal_reason=refusal_reason,
        ranked=state.get("ranked", []),
        top=state.get("top", []),
        timings=timings if timings is not None else state.get("timings", {}),
    )


def _model_rerank_score(top):
    scores = [
        float(item["rerank_score"])
        for item in top
        if item.get("rerank_mode") == "model" and item.get("rerank_score") is not None
    ]
    return max(scores) if scores else None


def _has_grounded_evidence(question, top):
    # 模型重排可用时，最高重排 logits 比向量相似度更能区分“有依据”和“只是字面接近”：
    # golden set 上 > 0 能保留全部可回答样本，同时挡住不可回答样本。
    # 重排被关闭或加载失败时，退回下面的向量/BM25 门槛。
    rerank_score = _model_rerank_score(top)
    if rerank_score is not None:
        return rerank_score > config.MIN_RERANK_SCORE

    # SQLite 的 bm25() 越小越相关。词面重合用来挡住只撞上一个常见二字的假命中。
    # 具体门槛：
    # - 向量侧：余弦相似度 >= MIN_VECTOR_SCORE（默认 0.35，按 bge-small-zh 标定）；
    # - BM25 侧：bm25() < -0.05 且查询词覆盖率 >= 0.18，两个条件必须同时满足，
    #   单独一个很弱的相关性不算证据。
    # 换嵌入模型或分词方式后，这三个阈值都需要重新标定。
    vector_evidence = any((item.get("vector_score") or 0) >= config.MIN_VECTOR_SCORE for item in top)
    bm25_evidence = any(
        (item.get("bm25_score") or 0) < -0.05 and _lexical_score(question, item["text"]) >= 0.18
        for item in top
    )
    return bool(top and (vector_evidence or bm25_evidence))


def _rewrite_query(question):
    """只返回一条检索查询，不在这里生成回答。失败或和原问题相同则返回空字符串。"""
    try:
        rewritten = llm.generate(
            "你是企业知识库检索查询改写器。只输出一条简短、保留原意的检索查询；"
            "不要回答问题，不要添加原问题没有的事实。",
            f"原问题：{question}\n请改写为更适合知识库检索的一句话：",
        ).strip()
    except Exception:
        return ""
    rewritten = rewritten.splitlines()[0].strip().strip("\"'`“”‘’ ") if rewritten else ""
    for prefix in ("改写问题：", "检索查询：", "查询："):
        if rewritten.startswith(prefix):
            rewritten = rewritten[len(prefix):].strip()
    if not rewritten or len(rewritten) > 240 or rewritten == question.strip():
        return ""
    return rewritten


def _retrieval_metrics(libraries, ranked, top, query_rewrites=0):
    return {
        "libraries": libraries,
        "vector_hits": len([item for item in ranked if item.get("vector_score") is not None]),
        "bm25_hits": len([item for item in ranked if item.get("bm25_score") is not None]),
        "reranked": len(ranked),
        "top_k": len(top),
        "query_rewrites": query_rewrites,
    }


def _refusal(question, user_id, libraries, reason, retrieval=None, conversation_id=None,
             ranked=None, top=None, queries=None, timings=None):
    # 拒答也写入 answers，保证历史对话完整；sources 为空、grounded=False。
    messages = {
        "no_approved_permission": (
            "当前账号还没有任何已审批的知识库权限，暂不作答。"
            "请先申请对应知识库权限，或联系管理员审批。"
        ),
        "no_grounded_evidence": (
            "已授权知识库中没有检索到足够匹配的文档依据，暂不作答。"
            "请换用文档中的关键词或补充更具体的问题。"
        ),
    }
    answer = messages.get(reason, "当前授权知识库没有足够依据，暂不作答。")
    answer_id = db.create_answer(user_id, question, answer, "[]", conversation_id)
    conv_id = db.conversation_id_for_answer(answer_id)
    trace_queries = queries or [question]
    trace_id = tracing.record_safely(
        answer_id=answer_id,
        user_id=user_id,
        conversation_id=conv_id,
        question=question,
        queries=trace_queries,
        retrieval_query=question,
        query_rewrites=max(0, len(trace_queries) - 1),
        libraries=libraries,
        grounded=False,
        refusal_reason=reason,
        ranked=ranked or [],
        top=top or [],
        timings=timings or {},
    )
    return {
        "answer_id": answer_id,
        "conversation_id": conv_id,
        "trace_id": trace_id,
        "answer": answer, "answer_html": md_render.render(answer), "sources": [],
        "grounded": False, "refusal_reason": reason,
        "retrieval": retrieval or {"libraries": libraries, "vector_hits": 0, "bm25_hits": 0, "reranked": 0},
    }


def _ask_legacy(question, user_id):
    # langgraph 不可用时的兼容路径。检索、拒答和来源锚点要与 _graph_ground 保持一致。
    libraries = db.approved_permissions(user_id)
    if not libraries:
        return _refusal(question, user_id, [], "no_approved_permission")

    ranked = _hybrid_search(question, libraries)
    top = ranked[: config.RERANK_TOP_K]
    rewrite_count = 0
    if not _has_grounded_evidence(question, top):
        rewritten = _rewrite_query(question) if config.RAG_QUERY_REWRITE_LIMIT else ""
        if rewritten:
            rewrite_count += 1
            ranked = _hybrid_search(rewritten, libraries)
            top = ranked[: config.RERANK_TOP_K]
    if not _has_grounded_evidence(question, top):
        return _refusal(
            question, user_id, libraries, "no_grounded_evidence",
            _retrieval_metrics(libraries, ranked, top, rewrite_count),
            ranked=ranked, top=top,
            queries=[question] + ([rewritten] if rewrite_count else []),
        )
    sources = []
    context_parts = []
    for index, item in enumerate(top, start=1):
        sources.append(_source_dict(index, item))
        context_parts.append(f"[{index}]【知识库: {item.get('library', '')} | 来源: {_source_label(item)}】\n{item['text']}")
    context = "\n\n---\n\n".join(context_parts)
    recent = db.recent_answers(user_id, 3)
    recent_text = "\n".join(f"- 用户曾问：{row['question']}" for row in recent)
    user_prompt = (
        f"问题：{question}\n\n"
        f"最近问题（仅保持上下文，不可作为事实来源）：\n{recent_text or '无'}\n\n"
        f"{_fewshot_block({'libraries': libraries})}"
        f"参考资料（只能引用这些编号）：\n{context}"
    )
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    answer = llm.generate(SYSTEM_PROMPT, user_prompt)
    answer_id = db.create_answer(user_id, question, answer, json.dumps(sources, ensure_ascii=False))
    conversation_id = db.conversation_id_for_answer(answer_id)
    trace_id = _record_trace(
        {
            "user_id": user_id,
            "question": question,
            "retrieval_query": rewritten if rewrite_count else question,
            "rewrite_count": rewrite_count,
            "libraries": libraries,
            "ranked": ranked,
            "top": top,
        },
        answer_id,
        True,
    )
    return {
        "answer_id": answer_id,
        "conversation_id": conversation_id,
        "trace_id": trace_id,
        "answer": answer, "answer_html": md_render.render(answer), "sources": sources,
        "grounded": True,
        "retrieval": {"libraries": libraries, "vector_hits": len([x for x in ranked if x.get("vector_score") is not None]),
                       "bm25_hits": len([x for x in ranked if x.get("bm25_score") is not None]),
                       "reranked": len(ranked), "top_k": len(top)},
    }


# ---- LangGraph 工作流 ----
try:
    from typing import TypedDict
    from langgraph.graph import END, START, StateGraph
except ImportError:  # 允许旧环境在未安装 langgraph 时使用兼容回退路径
    END = START = StateGraph = None

    class TypedDict(dict):
        pass


class RagState(TypedDict, total=False):
    question: str
    retrieval_query: str
    rewrite_count: int
    needs_rewrite: bool
    user_id: int
    libraries: list[str]
    ranked: list[dict]
    top: list[dict]
    sources: list[dict]
    context: str
    answer: str
    result: dict
    stop: bool
    refusal_reason: str


def _graph_authorize(state):
    libraries = db.approved_permissions(state["user_id"])
    if not libraries:
        return {
            "libraries": [],
            "stop": True,
            "result": _refusal(
                state["question"], state["user_id"], [], "no_approved_permission",
                conversation_id=state.get("conversation_id"),
                timings=_timings(state),
            ),
        }
    return {"libraries": libraries, "stop": False}


def _graph_retrieve(state):
    query = state.get("retrieval_query") or state["question"]
    ranked = _hybrid_search(query, state["libraries"])
    return {"ranked": ranked, "top": ranked[: config.RERANK_TOP_K]}


def _graph_ground(state):
    top = state.get("top", [])
    if not _has_grounded_evidence(state["question"], top):
        if state.get("rewrite_count", 0) < config.RAG_QUERY_REWRITE_LIMIT:
            return {"needs_rewrite": True, "stop": False}
        return {
            "stop": True,
            "needs_rewrite": False,
            "refusal_reason": "no_grounded_evidence",
            "result": _refusal(
                state["question"], state["user_id"], state["libraries"],
                "no_grounded_evidence",
                _retrieval_metrics(
                    state["libraries"], state.get("ranked", []), top,
                    state.get("rewrite_count", 0),
                ),
                conversation_id=state.get("conversation_id"),
                ranked=state.get("ranked", []),
                top=top,
                queries=_trace_queries(state),
                timings=_timings(state),
            ),
        }

    sources = []
    context_parts = []
    for index, item in enumerate(top, start=1):
        sources.append(_source_dict(index, item))
        context_parts.append(
            f"[{index}]【知识库: {item.get('library', '')} | 来源: {_source_label(item)}】\n{item['text']}"
        )
    return {
        "sources": sources,
        "context": "\n\n---\n\n".join(context_parts),
        "stop": False,
        "needs_rewrite": False,
    }


def _graph_rewrite(state):
    rewritten = _rewrite_query(state["question"])
    if not rewritten:
        result = _refusal(
            state["question"], state["user_id"], state["libraries"],
            "no_grounded_evidence",
            _retrieval_metrics(
                state["libraries"], state.get("ranked", []), state.get("top", []),
                state.get("rewrite_count", 0),
            ),
            conversation_id=state.get("conversation_id"),
            ranked=state.get("ranked", []),
            top=state.get("top", []),
            queries=_trace_queries(state),
            timings=_timings(state),
        )
        return {"stop": True, "needs_rewrite": False, "result": result}
    return {
        "retrieval_query": rewritten,
        "rewrite_count": state.get("rewrite_count", 0) + 1,
        "needs_rewrite": False,
        "stop": False,
    }


def _fewshot_block(state):
    # 只在全局开关打开、且示例已审核时注入；示例不是事实来源，也不是引用编号。
    if not config.CURATED_FEWSHOT_ENABLED:
        return ""
    examples = curated_store.approved_examples(
        config.CURATED_FEWSHOT_LIMIT, state.get("libraries") or []
    )
    if not examples:
        return ""
    text = "\n\n".join(
        f"示例问题：{item['question']}\n示例回答：{item['answer']}"
        for item in examples
    )
    return (
        "表达示例（只学习结构和语气，不得作为事实来源，也不得引用其中编号）：\n"
        f"{text}\n\n"
    )


def _prompt_for_state(state):
    # 个人策略已下线；最近问题只用于同一组对话的上下文，不能作为事实来源。
    conversation_id = state.get("conversation_id")
    recent = db.recent_answers(state["user_id"], 3, conversation_id) if conversation_id else []
    recent_text = "\n".join(f"- 用户曾问：{row['question']}" for row in recent)
    return (
        f"问题：{state['question']}\n\n"
        f"最近问题（仅保持上下文，不可作为事实来源）：\n{recent_text or '无'}\n\n"
        f"{_fewshot_block(state)}"
        f"参考资料（只能引用这些编号）：\n{state['context']}"
    )


def prepare(question, user_id, conversation_id=None):
    """完成授权、检索和证据判断，返回可生成回答的 state。

    返回有两种形态：
    - 拒答：包含完整 result 和 grounded=False，HTTP 层直接作为 JSON 返回；
    - 可生成：ready=True，带 user_prompt，由调用方流式生成后再调用 persist_prepared。
    这样 HTTP 层不需要再理解检索细节。
    """
    state = {
        "question": question,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "started_at": time.perf_counter(),
    }
    state.update(_graph_authorize(state))
    if state.get("stop"):
        return state["result"]
    while True:
        state.update(_graph_retrieve(state))
        state.update(_graph_ground(state))
        route = _route_after_ground(state)
        if route == "stop":
            return state["result"]
        if route == "rewrite":
            state.update(_graph_rewrite(state))
            if state.get("stop"):
                return state["result"]
            continue
        break
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    state["user_prompt"] = _prompt_for_state(state)
    state["timings"] = {"prepare_ms": int((time.perf_counter() - state["started_at"]) * 1000)}
    state["ready"] = True
    return state


def persist_prepared(state, answer, generation_ms=None):
    # 与 prepare 配对：生成结束后统一落库并组装 answer_html/sources/retrieval。
    # 流式接口必须在发送 done 之前调用，保证前端拿到的 answer_id 可以评价。
    timings = dict(state.get("timings") or {})
    if generation_ms is not None:
        timings["generation_ms"] = int(generation_ms)
    return _graph_persist({**state, "answer": answer, "timings": timings})["result"]


def _graph_generate(state):
    user_prompt = _prompt_for_state(state)
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")
    return {"answer": llm.generate(SYSTEM_PROMPT, user_prompt), "stop": False}


def _graph_persist(state):
    sources = state["sources"]
    answer = state["answer"]
    answer_id = db.create_answer(
        state["user_id"], state["question"], answer, json.dumps(sources, ensure_ascii=False),
        state.get("conversation_id"),
    )
    conversation_id = db.conversation_id_for_answer(answer_id)
    trace_id = _record_trace(state, answer_id, True)
    return {
        "result": {
            "answer_id": answer_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "answer": answer,
            "answer_html": md_render.render(answer),
            "sources": sources,
            "grounded": True,
            "retrieval": _retrieval_metrics(
                state["libraries"], state.get("ranked", []), state.get("top", []),
                state.get("rewrite_count", 0),
            ),
        }
    }


def _route_after_check(state):
    return "stop" if state.get("stop") else "continue"


def _route_after_ground(state):
    if state.get("stop"):
        return "stop"
    return "rewrite" if state.get("needs_rewrite") else "continue"


def _route_after_rewrite(state):
    return "stop" if state.get("stop") else "continue"


def _build_rag_graph():
    # 开启改写时形成 ground → rewrite → retrieve 的回边，回边次数由 rewrite_count 限制。
    if StateGraph is None:
        return None
    try:
        graph = StateGraph(RagState)
        graph.add_node("authorize", _graph_authorize)
        graph.add_node("retrieve", _graph_retrieve)
        graph.add_node("ground", _graph_ground)
        graph.add_node("rewrite", _graph_rewrite)
        graph.add_node("generate", _graph_generate)
        graph.add_node("persist", _graph_persist)
        graph.add_edge(START, "authorize")
        graph.add_conditional_edges("authorize", _route_after_check, {"stop": END, "continue": "retrieve"})
        graph.add_edge("retrieve", "ground")
        graph.add_conditional_edges(
            "ground", _route_after_ground,
            {"stop": END, "rewrite": "rewrite", "continue": "generate"},
        )
        graph.add_conditional_edges("rewrite", _route_after_rewrite, {"stop": END, "continue": "retrieve"})
        graph.add_edge("generate", "persist")
        graph.add_edge("persist", END)
        return graph.compile()
    except Exception:
        return None


_RAG_GRAPH = _build_rag_graph()


def ask(question, user_id):
    if _RAG_GRAPH is None:
        return _ask_legacy(question, user_id)
    state = _RAG_GRAPH.invoke({"question": question, "user_id": user_id})
    return state["result"]
