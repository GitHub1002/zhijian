"""规则分流：来源级标记要能单独触发归因。"""
from app import feedback


def test_positive_always_wins():
    category, confidence, _ = feedback.classify(
        {"sentiment": "positive", "reasons": ["helpful"]}, {}
    )
    assert category == "positive"
    assert confidence == 0.9


def test_irrelevant_source_mark_routes_to_retrieval():
    category, confidence, _ = feedback.classify(
        {
            "sentiment": "negative",
            "reasons": ["wrong_info"],
            "source_marks": [{"mark": "irrelevant"}],
        },
        {"grounded": True, "best_rerank_score": 4.0},
    )
    assert category == "retrieval_failure"
    assert confidence == 0.8


def test_missing_context_mark_routes_to_retrieval():
    category, _, _ = feedback.classify(
        {
            "sentiment": "negative",
            "reasons": ["incomplete"],
            "source_marks": [{"mark": "missing_context"}],
        },
        {"grounded": True},
    )
    assert category == "retrieval_failure"


def test_explicit_reason_beats_trace_inference():
    category, confidence, _ = feedback.classify(
        {"sentiment": "negative", "reasons": ["outdated"]},
        {"grounded": True, "best_rerank_score": 4.0},
    )
    assert category == "doc_issue"
    assert confidence == 0.9
