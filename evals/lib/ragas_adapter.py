"""可选的 RAGAS 适配层。只在 `--provider ragas` 时导入。

RAGAS 需要额外配置 LLM/Embedding。未安装或未配置时抛出明确错误，
不会静默降级；默认路径使用 `--provider simple` 的 LLM Judge。
"""


def _llm():
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    from app import config

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("RAGAS 需要 DEEPSEEK_API_KEY 来充当裁判模型")
    return LangchainLLMWrapper(
        ChatOpenAI(
            model=config.DEEPSEEK_MODEL,
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            temperature=0,
            timeout=60,
            max_retries=2,
        )
    )


def _embeddings():
    from langchain_core.embeddings import Embeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    from app import embedder

    class _LocalEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return embedder.embed_documents(texts)

        def embed_query(self, text):
            return embedder.embed_query(text)

    return LangchainEmbeddingsWrapper(_LocalEmbeddings())


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
            "或改用 --provider simple。"
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
        llm=_llm(),
        embeddings=_embeddings(),
    )
    try:
        return result.to_pandas().to_dict(orient="records")
    except Exception:
        return dict(result)
