"""RAG 回答质量评测。

默认使用 `--provider simple`：用现有 DeepSeek 做 LLM-as-judge，不需要额外依赖。
`--provider ragas` 走 RAGAS，需要先安装 evals/requirements-eval.txt 并配置 LLM。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.lib.dataset import load_cases  # noqa: E402
from evals.lib.report import write_json  # noqa: E402

JUDGE_SYSTEM = "你是严格的 RAG 评测员，只输出 JSON，不要解释。"
JUDGE_KEYS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
REFUSAL_MARKERS = ("暂不作答", "没有足够依据", "无法回答", "没有相关")


def _parse_json(text):
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("judge 没有返回 JSON")
    data = json.loads(text[start:end + 1])
    scores = {}
    for key in JUDGE_KEYS:
        value = data.get(key)
        if value is None:
            scores[key] = None
        else:
            scores[key] = max(0.0, min(1.0, float(value)))
    scores["notes"] = str(data.get("notes") or "")
    return scores


def _judge_prompt(case, answer, contexts):
    blocks = "\n".join(f"[{index + 1}] {text}" for index, text in enumerate(contexts))
    return (
        "请给下面这次 RAG 回答打分，分数范围 0 到 1，只输出 JSON：\n"
        '{"faithfulness":0.0,"answer_relevancy":0.0,'
        '"context_precision":0.0,"context_recall":0.0,"notes":""}\n\n'
        f"问题：{case['question']}\n"
        f"参考答案：{case.get('reference_answer') or '（无）'}\n"
        f"回答：{answer}\n"
        f"参考资料：\n{blocks}"
    )


def _generate_answer(llm, rag, question, contexts):
    blocks = "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(contexts))
    prompt = (
        f"问题：{question}\n\n"
        f"参考资料（只能引用这些编号）：\n{blocks}"
    )
    return llm.generate(rag.SYSTEM_PROMPT, prompt)


RAGAS_KEYS = (
    ("faithfulness", "faithfulness"),
    ("answer_relevancy", "answer_relevancy"),
    ("llm_context_precision_with_reference", "context_precision"),
    ("context_recall", "context_recall"),
)


def _aggregate(rows):
    summary = {"cases": len(rows), "errors": sum(1 for row in rows if row.get("error"))}
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    summary["answerable_cases"] = len(answerable)
    summary["unanswerable_cases"] = len(unanswerable)
    for key in JUDGE_KEYS:
        values = [
            row["scores"].get(key)
            for row in answerable
            if row.get("scores") and row["scores"].get(key) is not None
        ]
        summary[key] = round(sum(values) / len(values), 4) if values else None
    if unanswerable:
        refused = sum(1 for row in unanswerable if row.get("refused"))
        summary["correct_refusal_rate"] = round(refused / len(unanswerable), 4)
    return summary


def _ragas_summary(records):
    summary = {"cases": len(records)}
    for source_key, target_key in RAGAS_KEYS:
        values = [
            float(record[source_key])
            for record in records
            if isinstance(record.get(source_key), (int, float))
        ]
        summary[target_key] = round(sum(values) / len(values), 4) if values else None
    return summary


def main():
    parser = argparse.ArgumentParser(description="RAG 回答质量评测")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--include-hard-negatives", action="store_true",
        help="配合 --limit：截断后仍保留全部不可回答样本",
    )
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--provider", choices=["simple", "ragas"], default="simple")
    parser.add_argument("--out")
    parser.add_argument("--db-path")
    parser.add_argument("--qdrant-path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.db_path:
        os.environ["DB_PATH"] = args.db_path
    if args.qdrant_path:
        os.environ["QDRANT_PATH"] = args.qdrant_path

    all_cases = load_cases(args.dataset)
    cases = all_cases[: args.limit]
    if args.include_hard_negatives:
        seen = {case["case_id"] for case in cases}
        cases += [
            case for case in all_cases
            if not case["answerable"] and case["case_id"] not in seen
        ]

    if args.dry_run:
        rows = [
            {
                "case_id": case["case_id"],
                "question": case["question"],
                "answerable": case["answerable"],
                "answer": "",
                "contexts": [],
                "scores": {key: None for key in JUDGE_KEYS},
                "refused": False,
                "error": "",
            }
            for case in cases
        ]
    else:
        from app import llm, rag  # noqa: E402

        rows = []
        total = len(cases)
        for position, case in enumerate(cases, start=1):
            print(
                f"  [{position}/{total}] {case['case_id']} 检索与生成…",
                flush=True,
            )
            row = {
                "case_id": case["case_id"],
                "question": case["question"],
                "answerable": case["answerable"],
                "answer": "",
                "contexts": [],
                "scores": {},
                "refused": False,
                "error": "",
            }
            try:
                retrieved = rag._hybrid_search(
                    case["question"], [case["library"]] if case["library"] else []
                )[: args.k]
                contexts = [item.get("text", "") for item in retrieved]
                row["contexts"] = contexts
                row["retrieved"] = [
                    {
                        "chunk_id": item.get("chunk_id"),
                        "source": item.get("source"),
                        "heading": item.get("heading"),
                        "vector_score": item.get("vector_score"),
                        "bm25_score": item.get("bm25_score"),
                        "rerank_score": item.get("rerank_score"),
                    }
                    for item in retrieved
                ]
                answer = _generate_answer(llm, rag, case["question"], contexts)
                row["answer"] = answer
                row["refused"] = any(marker in answer for marker in REFUSAL_MARKERS)
                if case["answerable"] and args.provider == "simple":
                    judged = llm.generate(
                        JUDGE_SYSTEM, _judge_prompt(case, answer, contexts)
                    )
                    row["scores"] = _parse_json(judged)
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)

    summary = _aggregate(rows)
    payload = {
        "provider": args.provider,
        "dataset": str(Path(args.dataset).resolve()),
        "limit": args.limit,
        "k": args.k,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": summary,
        "cases": rows,
    }

    if args.provider == "ragas" and not args.dry_run:
        print("\n  生成完成，开始 RAGAS 评分…", flush=True)
        from evals.lib.ragas_adapter import run_ragas  # noqa: E402

        samples = [
            {
                "user_input": row["question"],
                "retrieved_contexts": row["contexts"],
                "response": row["answer"],
                "reference": case.get("reference_answer", ""),
            }
            for row, case in zip(rows, cases)
            if row["answerable"] and not row["error"]
        ]
        ragas_records = run_ragas(samples)
        payload["ragas"] = ragas_records
        payload["ragas_summary"] = _ragas_summary(ragas_records)
        # 让 aggregate 也能被 check_thresholds 直接读取。
        for key in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            summary[key] = payload["ragas_summary"].get(key)

    out = Path(args.out) if args.out else (
        ROOT / "evals" / "reports" / f"ragas_{args.provider}.json"
    )
    write_json(out, payload)
    print(f"\nRAG EVAL · {args.provider}")
    print("=" * 24)
    if args.provider == "ragas" and payload.get("ragas_summary"):
        ragas_summary = payload["ragas_summary"]
        for key in ("faithfulness", "answer_relevancy", "context_precision",
                    "context_recall", "cases"):
            print(f"  {key:22} {ragas_summary.get(key)}")
    else:
        for key in JUDGE_KEYS:
            print(f"  {key:22} {summary.get(key)}")
    print(f"  {'correct_refusal_rate':22} {summary.get('correct_refusal_rate')}")
    print(f"  {'errors':22} {summary.get('errors')}")
    print(f"\n  report: {out}")

    if not args.dry_run:
        try:
            from app import store  # noqa: E402

            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
