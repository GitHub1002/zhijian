"""参数扫描：组合展开、签名分组、缓存评估和证据门槛。"""
from evals.lib.runner import aggregate, evaluate_cached
from evals.lib.sweep import expand_sweep, has_evidence, signature_keys, signature_of

SPEC = {
    "base": {"RERANK_TOP_K": 3},
    "signatures": [
        {"RRF_K": 20, "HYBRID_TOP_K": 12},
        {"RRF_K": 60, "HYBRID_TOP_K": 12},
    ],
    "gates": {"MIN_RERANK_SCORE": [-2.0, 0.0, 0.5]},
}


def _case(answerable, expected_sources=None):
    return {
        "case_id": "c1",
        "question": "年假多少天",
        "library": "hr",
        "answerable": answerable,
        "hard_negative": not answerable,
        "expected_sources": expected_sources or [],
        "reference_answer": "",
        "tags": [],
    }


def test_expand_sweep_multiplies_signatures_and_gates():
    configs = expand_sweep(SPEC)

    assert len(configs) == 6
    assert {config["RRF_K"] for config in configs} == {20, 60}
    assert {config["MIN_RERANK_SCORE"] for config in configs} == {-2.0, 0.0, 0.5}
    assert all(config["RERANK_TOP_K"] == 3 for config in configs)


def test_signature_keys_and_grouping():
    keys = signature_keys(SPEC)
    assert keys == ["HYBRID_TOP_K", "RRF_K"]
    assert signature_of({"RRF_K": 60, "HYBRID_TOP_K": 12}, keys) == (12, 60)


def test_model_rerank_negative_rejects_even_with_high_vector():
    item = {
        "text": "公司年会安排",
        "vector_score": 0.52,
        "bm25_score": -0.8,
        "rerank_score": -4.2,
        "rerank_mode": "model",
    }
    assert has_evidence("公司年会在哪里举办", [item], 0.0, 0.35, lambda q, t: 1.0) is False


def test_lexical_fallback_uses_vector_and_bm25_gate():
    lexical = lambda question, text: 0.5  # noqa: E731
    bigram = {"text": "年假", "vector_score": 0.1, "bm25_score": -1.0,
              "rerank_score": 0.0, "rerank_mode": "lexical"}
    weak = {"text": "年会", "vector_score": 0.1, "bm25_score": 0.0,
            "rerank_score": 0.0, "rerank_mode": "lexical"}

    assert has_evidence("年假", [bigram], 0.0, 0.35, lexical) is True
    assert has_evidence("年假", [weak], 0.0, 0.35, lexical) is False


def test_evaluate_cached_reuses_retrieved_results():
    cases = [_case(True, [{"source": "hr/leave.md", "heading": "年假"}])]
    retrieved = {"c1": [{"source": "hr/leave.md", "heading": "年假"}]}

    rows = evaluate_cached(
        cases, retrieved, lambda question, top: True, (1,), "source_heading",
        evidence_top_k=1,
    )
    summary = aggregate(rows)

    assert summary["hit@1"] == 1.0
    assert summary["false_refusal_rate"] == 0.0
    assert rows[0]["latency_ms"] == 0


def test_cached_unanswerable_can_be_falsely_answered():
    cases = [_case(False)]
    retrieved = {"c1": [{"source": "hr/leave.md", "heading": "年假"}]}
    rows = evaluate_cached(
        cases, retrieved, lambda question, top: True, (1,), "source_heading"
    )

    assert aggregate(rows)["false_answer_rate"] == 1.0
