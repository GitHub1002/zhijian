"""评测执行器：把 search/evidence 注入，跑 case 并汇总指标。"""
import time

from . import metrics


def evaluate_retrieval(cases, search, evidence=None, k_values=(3, 5, 12),
                       match="source_heading"):
    results = []
    top_k = max(k_values)
    for case in cases:
        started = time.perf_counter()
        error = ""
        try:
            retrieved = list(search(case["question"], case.get("library")))
        except Exception as exc:  # 单个 case 失败不应中断整批评测
            retrieved = []
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = int((time.perf_counter() - started) * 1000)
        top = retrieved[:top_k]

        row = {
            "case_id": case["case_id"],
            "question": case["question"],
            "library": case["library"],
            "answerable": case["answerable"],
            "hard_negative": case["hard_negative"],
            "expected_sources": case["expected_sources"],
            "retrieved": top[:12],
            "latency_ms": latency_ms,
            "error": error,
            "metrics": {},
        }
        if case["answerable"] and case["expected_sources"]:
            row["metrics"] = metrics.evaluate_case(
                top, case["expected_sources"], k_values, match
            )
        if evidence is not None:
            try:
                row["grounded"] = bool(evidence(case["question"], top))
            except Exception:
                row["grounded"] = None
        results.append(row)
    return results


def aggregate(results):
    metric_keys = set()
    for row in results:
        metric_keys.update(row.get("metrics", {}).keys())
    summary = {}
    for key in sorted(metric_keys):
        values = [
            row["metrics"][key]
            for row in results
            if row.get("metrics", {}).get(key) is not None
        ]
        summary[key] = round(sum(values) / len(values), 4) if values else None

    answerable = [row for row in results if row["answerable"]]
    unanswerable = [row for row in results if not row["answerable"]]
    summary["answerable_cases"] = len(answerable)
    summary["unanswerable_cases"] = len(unanswerable)
    summary["errors"] = sum(1 for row in results if row["error"])

    latencies = [row["latency_ms"] for row in results if row["latency_ms"] is not None]
    summary["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else None
    summary["cases_with_vector_hits"] = sum(
        1
        for row in results
        if any(item.get("vector_score") is not None for item in row.get("retrieved", []))
    )

    if unanswerable and any("grounded" in row for row in unanswerable):
        correct = sum(1 for row in unanswerable if row.get("grounded") is False)
        false_answer = sum(1 for row in unanswerable if row.get("grounded") is True)
        summary["correct_refusal_rate"] = round(correct / len(unanswerable), 4)
        summary["false_answer_rate"] = round(false_answer / len(unanswerable), 4)
    if answerable and any("grounded" in row for row in answerable):
        refused = sum(1 for row in answerable if row.get("grounded") is False)
        summary["false_refusal_rate"] = round(refused / len(answerable), 4)
    return summary
