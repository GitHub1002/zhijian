"""证据门槛：模型重排可用时看重排 logits，不可用时退回向量/BM25。"""
from app import config, rag


def _item(**overrides):
    item = {
        "text": "员工年假天数按工龄计算",
        "vector_score": 0.9,
        "bm25_score": -1.0,
        "rerank_score": 1.0,
        "rerank_mode": "model",
    }
    item.update(overrides)
    return item


class _FakeReranker:
    def __init__(self, scores):
        self.scores = scores

    def rerank(self, question, texts):
        return self.scores


def test_positive_rerank_keeps_answerable_case():
    assert rag._has_grounded_evidence("年假多少天", [_item()]) is True


def test_negative_rerank_rejects_even_with_high_vector_score():
    # 不可回答样本常见：向量分数过线，但重排 logits 明显为负。
    item = _item(rerank_score=-4.2, vector_score=0.52, bm25_score=-0.8)
    assert rag._has_grounded_evidence("公司年会在哪里举办", [item]) is False


def test_rerank_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "MIN_RERANK_SCORE", 2.0)
    assert rag._has_grounded_evidence("年假多少天", [_item(rerank_score=1.5)]) is False
    assert rag._has_grounded_evidence("年假多少天", [_item(rerank_score=2.5)]) is True


def test_lexical_fallback_keeps_vector_gate():
    item = _item(rerank_mode="lexical", rerank_score=0.0, vector_score=0.5)
    assert rag._has_grounded_evidence("年假多少天", [item]) is True

    weak = _item(
        rerank_mode="lexical", rerank_score=0.0,
        vector_score=0.1, bm25_score=0.0,
    )
    assert rag._has_grounded_evidence("年假多少天", [weak]) is False


def test_empty_candidates_are_not_grounded():
    assert rag._has_grounded_evidence("年假多少天", []) is False


def test_rerank_marks_model_mode(monkeypatch):
    monkeypatch.setattr(rag, "_get_reranker", lambda cfg=None: _FakeReranker([3.0, -1.0]))
    candidates = [{"text": "年假"}, {"text": "年会"}]
    ordered = rag._rerank("年假", candidates)

    assert [item["rerank_mode"] for item in ordered] == ["model", "model"]
    assert ordered[0]["text"] == "年假"
    assert ordered[0]["rerank_score"] == 3.0


def test_rerank_marks_lexical_mode_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(rag, "_get_reranker", lambda cfg=None: False)
    candidates = [{"text": "年假", "rrf_score": 0.1}]
    ordered = rag._rerank("年假", candidates)

    assert ordered[0]["rerank_mode"] == "lexical"
    assert ordered[0]["rerank_score"] > 0
