"""评测报告输出与对比。"""
import json
from pathlib import Path


def write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_summary(summary, title="RETRIEVAL EVAL"):
    print(f"\n{title}")
    print("=" * len(title))
    keys = [
        "hit@3", "hit@5", "hit@12",
        "recall@3", "recall@5", "recall@12",
        "precision@5", "ndcg@5", "ndcg@12", "mrr", "ap",
        "correct_refusal_rate", "false_answer_rate", "false_refusal_rate",
        "avg_latency_ms", "cases_with_vector_hits",
        "answerable_cases", "unanswerable_cases", "errors",
    ]
    for key in keys:
        if key in summary:
            print(f"  {key:22} {_fmt(summary[key])}")
    extra = [key for key in summary if key not in keys]
    for key in extra:
        print(f"  {key:22} {_fmt(summary[key])}")


def _higher_is_better(key):
    return (
        key.startswith(("hit@", "recall@", "precision@", "ndcg@"))
        or key in {"mrr", "ap", "correct_refusal_rate"}
    )


def print_comparison(baseline, candidate, max_drop=0.02):
    print("\nBASELINE → CANDIDATE")
    print("=" * 32)
    keys = sorted(set(baseline) | set(candidate))
    regressions = []
    for key in keys:
        if key in {"avg_latency_ms", "errors"} or key.endswith("_cases"):
            continue
        if not isinstance(candidate.get(key), (int, float)):
            continue
        old = baseline.get(key)
        new = candidate.get(key)
        if not isinstance(old, (int, float)):
            continue
        delta = new - old
        flag = ""
        if _higher_is_better(key) and delta < -max_drop:
            flag = "  REGRESSION"
            regressions.append((key, old, new, delta))
        print(f"  {key:22} {_fmt(old):>10} → {_fmt(new):>10} ({delta:+.4f}){flag}")
    return regressions
