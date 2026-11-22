import math

from evals.lib.metrics import (
    average_precision,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

RETRIEVED = [
    {"source": "a.md", "heading": "一"},
    {"source": "b.md", "heading": "二"},
    {"source": "b.md", "heading": "二"},
]
EXPECTED = [{"source": "b.md", "heading": "二"}]


def test_hit_at_k_respects_cutoff():
    assert hit_at_k(RETRIEVED, EXPECTED, 1) == 0.0
    assert hit_at_k(RETRIEVED, EXPECTED, 2) == 1.0


def test_recall_and_precision():
    assert recall_at_k(RETRIEVED, EXPECTED, 3) == 1.0
    assert precision_at_k(RETRIEVED, EXPECTED, 3) == 1 / 3


def test_mrr_and_ndcg():
    assert mrr_at_k(RETRIEVED, EXPECTED, 3) == 0.5
    assert abs(ndcg_at_k(RETRIEVED, EXPECTED, 3) - 1 / math.log2(3)) < 1e-9


def test_duplicate_sections_do_not_inflate_ap_or_ndcg():
    # 同一 source+heading 的多个切块只算一次命中，避免 AP/NDCG > 1。
    assert abs(average_precision(RETRIEVED, EXPECTED, 3) - 0.5) < 1e-9
    assert 0.0 <= ndcg_at_k(RETRIEVED, EXPECTED, 3) <= 1.0
    assert 0.0 <= average_precision(RETRIEVED, EXPECTED, 3) <= 1.0


def test_empty_expected_returns_none():
    assert hit_at_k(RETRIEVED, [], 3) is None
    assert recall_at_k(RETRIEVED, [], 3) is None
    assert mrr_at_k(RETRIEVED, [], 3) is None
