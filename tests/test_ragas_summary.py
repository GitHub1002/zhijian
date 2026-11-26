"""RAGAS 结果汇总：兼容 0.2 的 context_precision 字段名。"""
from evals.run_ragas_eval import _ragas_summary


def test_ragas_summary_maps_context_precision():
    records = [
        {
            "faithfulness": 1.0,
            "answer_relevancy": 0.8,
            "llm_context_precision_with_reference": 0.6,
            "context_recall": 0.4,
        },
        {
            "faithfulness": 0.8,
            "answer_relevancy": 0.6,
            "llm_context_precision_with_reference": 0.4,
            "context_recall": 0.2,
        },
    ]

    summary = _ragas_summary(records)

    assert summary["cases"] == 2
    assert summary["faithfulness"] == 0.9
    assert summary["answer_relevancy"] == 0.7
    assert summary["context_precision"] == 0.5
    assert summary["context_recall"] == 0.3


def test_ragas_summary_handles_empty_and_missing_values():
    assert _ragas_summary([])["faithfulness"] is None
    assert _ragas_summary([{}])["context_recall"] is None
