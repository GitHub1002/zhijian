"""参数扫描：展开配置组合，并在缓存结果上复现运行时的证据门槛。"""
import itertools


def expand_sweep(spec):
    """把 {base, signatures, gates} 展开成完整配置列表。"""
    base = dict(spec.get("base") or {})
    signatures = list(spec.get("signatures") or [{}])
    gates = dict(spec.get("gates") or {})
    gate_keys = list(gates)
    combos = (
        list(itertools.product(*(gates[key] for key in gate_keys)))
        if gate_keys else [()]
    )
    configs = []
    for signature in signatures:
        for combo in combos:
            config = {**base, **signature, **dict(zip(gate_keys, combo))}
            configs.append(config)
    return configs


def signature_keys(spec):
    keys = set()
    for signature in spec.get("signatures") or []:
        keys.update(signature)
    return sorted(keys)


def signature_of(config, keys):
    return tuple(config.get(key) for key in keys)


def has_evidence(question, top, min_rerank_score=0.0, min_vector_score=0.35,
                 lexical_score=None):
    """与 app.rag._has_grounded_evidence 一致，但门槛可注入。"""
    if not top:
        return False
    scores = [
        float(item["rerank_score"])
        for item in top
        if item.get("rerank_mode") == "model" and item.get("rerank_score") is not None
    ]
    if scores:
        return max(scores) > min_rerank_score

    vector_evidence = any(
        (item.get("vector_score") or 0) >= min_vector_score for item in top
    )
    bm25_evidence = bool(lexical_score) and any(
        (item.get("bm25_score") or 0) < -0.05
        and lexical_score(question, item.get("text", "")) >= 0.18
        for item in top
    )
    return vector_evidence or bm25_evidence


def make_evidence(config, lexical_score):
    min_rerank = float(config.get("MIN_RERANK_SCORE", 0.0))
    min_vector = float(config.get("MIN_VECTOR_SCORE", 0.35))
    return lambda question, top: has_evidence(
        question, top, min_rerank, min_vector, lexical_score
    )
