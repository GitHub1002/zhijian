import pytest

from app import feedback

SOURCES = [{"index": 1, "source": "hr/请假制度.md", "heading": "请假类型 > 年假"}]


def test_negative_requires_reason():
    with pytest.raises(ValueError):
        feedback.normalize({"sentiment": "negative", "reasons": []}, SOURCES)


def test_old_rating_payload_is_rejected():
    with pytest.raises(ValueError):
        feedback.normalize(
            {"rating": 2, "reason": "答非所问，没有引用文档"}, SOURCES
        )


def test_positive_defaults_to_helpful():
    result = feedback.normalize({"sentiment": "positive"}, SOURCES)
    assert result["sentiment"] == "positive"
    assert result["reasons"] == ["helpful"]


def test_unknown_reason_rejected():
    with pytest.raises(ValueError):
        feedback.normalize({"sentiment": "negative", "reasons": ["nope"]}, SOURCES)


def test_source_mark_index_must_be_in_range():
    with pytest.raises(ValueError):
        feedback.normalize(
            {
                "sentiment": "negative",
                "reasons": ["citation_wrong"],
                "source_marks": [{"source_index": 2, "mark": "wrong_citation"}],
            },
            SOURCES,
        )


def test_classify_retrieval_miss():
    category, confidence, _ = feedback.classify(
        {"sentiment": "negative", "reasons": ["retrieval_miss"]}, {}
    )
    assert category == "retrieval_failure"
    assert confidence >= 0.8


def test_classify_generation_failure_when_grounded():
    category, _, _ = feedback.classify(
        {"sentiment": "negative", "reasons": ["wrong_info"]},
        {"grounded": 1, "best_rerank_score": 0.8},
    )
    assert category == "generation_failure"
