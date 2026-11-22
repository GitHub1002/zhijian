"""可选的 RAGAS 适配层。只在 `--provider ragas` 时导入。

RAGAS 需要额外配置 LLM/Embedding。未安装或未配置时抛出明确错误，
不会静默降级；默认路径使用 `--provider simple` 的 LLM Judge。
"""


def run_ragas(samples):
    try:
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.metrics import (
            AnswerRelevancy,
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
        )
    except ImportError as exc:
        raise RuntimeError(
            "RAGAS 未安装。请先 pip install -r evals/requirements-eval.txt，"
            "并按 RAGAS 文档配置 LLM/Embedding；或改用 --provider simple。"
        ) from exc

    dataset = EvaluationDataset(
        samples=[SingleTurnSample(**sample) for sample in samples]
    )
    result = evaluate(
        dataset,
        metrics=[
            Faithfulness(),
            AnswerRelevancy(),
            LLMContextPrecisionWithReference(),
            LLMContextRecall(),
        ],
    )
    try:
        return result.to_pandas().to_dict(orient="records")
    except Exception:
        return dict(result)
