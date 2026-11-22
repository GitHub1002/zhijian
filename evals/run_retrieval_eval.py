"""离线检索评测。

示例：
  python evals/run_retrieval_eval.py --dataset evals/datasets/seed_v1.jsonl
  python evals/run_retrieval_eval.py --dataset ... --dry-run
  python evals/run_retrieval_eval.py --dataset ... --config '{"RRF_K": 40}' \
      --compare evals/reports/baseline.json
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
from evals.lib.report import print_comparison, print_summary, write_json  # noqa: E402
from evals.lib.runner import aggregate, evaluate_retrieval  # noqa: E402


def _parse_k(value):
    values = sorted({int(item) for item in value.split(",") if item.strip()})
    if not values:
        raise argparse.ArgumentTypeError("--k 至少需要一个整数")
    return tuple(values)


def _load_config(value):
    if not value:
        return {}
    text = Path(value).read_text(encoding="utf-8") if Path(value).exists() else value
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("--config 必须是 JSON 对象")
    return data


def _apply_config(config, overrides):
    applied = {}
    for key, value in overrides.items():
        if not hasattr(config, key):
            continue
        current = getattr(config, key)
        if isinstance(current, bool):
            applied[key] = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            applied[key] = int(value)
        elif isinstance(current, float):
            applied[key] = float(value)
        else:
            applied[key] = value
        setattr(config, key, applied[key])
    return applied


def main():
    parser = argparse.ArgumentParser(description="离线检索评测")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--k", type=_parse_k, default=(3, 5, 12))
    parser.add_argument("--name", default="retrieval")
    parser.add_argument("--out")
    parser.add_argument("--config")
    parser.add_argument("--compare")
    parser.add_argument("--max-drop", type=float, default=0.02)
    parser.add_argument("--fail-under-hit-rate", type=float)
    parser.add_argument("--db-path")
    parser.add_argument("--qdrant-path")
    parser.add_argument(
        "--match", choices=["source_heading", "chunk_id"], default="source_heading"
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--dry-run", action="store_true", help="不加载模型，用空检索验证 harness"
    )
    parser.add_argument(
        "--no-evidence", action="store_true", help="跳过 grounded 证据判断"
    )
    args = parser.parse_args()

    if args.db_path:
        os.environ["DB_PATH"] = args.db_path
    if args.qdrant_path:
        os.environ["QDRANT_PATH"] = args.qdrant_path

    cases = load_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]

    requested = _load_config(args.config)
    applied = {}
    if args.dry_run:
        search = lambda question, library: []  # noqa: E731
        evidence = None
    else:
        from app import config, rag  # noqa: E402

        applied = _apply_config(config, requested)
        search = lambda question, library: rag._hybrid_search(  # noqa: E731
            question, [library] if library else []
        )
        evidence = None if args.no_evidence else rag._has_grounded_evidence

    results = evaluate_retrieval(cases, search, evidence, args.k, args.match)
    summary = aggregate(results)

    payload = {
        "name": args.name,
        "dataset": str(Path(args.dataset).resolve()),
        "k": list(args.k),
        "match": args.match,
        "dry_run": args.dry_run,
        "config": {"requested": requested, "applied": applied},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "aggregate": summary,
        "cases": results,
    }
    out = Path(args.out) if args.out else ROOT / "evals" / "reports" / f"{args.name}.json"
    write_json(out, payload)
    print_summary(summary, f"RETRIEVAL EVAL · {args.name}")
    print(f"\n  report: {out}")

    if not args.dry_run:
        try:
            from app import store  # noqa: E402

            store.close()
        except Exception:
            pass

    failed = False
    if args.compare:
        baseline_payload = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        regressions = print_comparison(
            baseline_payload.get("aggregate", {}), summary, args.max_drop
        )
        failed = failed or bool(regressions)
    if args.fail_under_hit_rate is not None:
        hit_key = f"hit@{args.k[0]}"
        value = summary.get(hit_key)
        if value is None or value < args.fail_under_hit_rate:
            print(f"\n  FAIL: {hit_key}={value} < {args.fail_under_hit_rate}")
            failed = True
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
