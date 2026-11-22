"""离线检索参数扫描。

同一组检索参数只跑一次 golden set，再在缓存结果上评估不同证据门槛，
避免每个 MIN_RERANK_SCORE 都重新加载模型。

示例：
  python evals/run_sweep.py --dataset evals/datasets/seed_v1.jsonl --limit 30
  python evals/run_sweep.py --dataset evals/datasets/seed_v1.jsonl \
      --grid evals/configs/sweep_retrieval.json --out data/eval/sweep.json
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.lib.config import apply_config  # noqa: E402
from evals.lib.dataset import load_cases  # noqa: E402
from evals.lib.report import write_json  # noqa: E402
from evals.lib.runner import aggregate, evaluate_cached  # noqa: E402
from evals.lib.sweep import (  # noqa: E402
    expand_sweep,
    make_evidence,
    signature_keys,
    signature_of,
)

DEFAULT_GRID = ROOT / "evals" / "configs" / "sweep_retrieval.json"
METRIC_KEYS = (
    "hit@3", "hit@5", "recall@5", "precision@5", "mrr", "ndcg@5", "ap",
    "correct_refusal_rate", "false_answer_rate", "false_refusal_rate",
    "answerable_cases", "unanswerable_cases", "errors", "avg_latency_ms",
)


def _parse_k(value):
    values = sorted({int(item) for item in value.split(",") if item.strip()})
    if not values:
        raise argparse.ArgumentTypeError("--k 至少需要一个整数")
    return tuple(values)


def _load_spec(value):
    path = Path(value)
    text = path.read_text(encoding="utf-8") if path.exists() else value
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("--grid 必须是 JSON 对象")
    return data


def _retrieval_config(spec, config, keys):
    values = dict(spec.get("base") or {})
    for key in keys:
        if key in config:
            values[key] = config[key]
    return values


def _run_real(cases, configs, keys, spec, k_values):
    from app import config as app_config, rag  # noqa: E402

    groups = {}
    for config in configs:
        groups.setdefault(signature_of(config, keys), []).append(config)

    results = []
    for signature, group in groups.items():
        apply_config(app_config, _retrieval_config(spec, group[0], keys))
        cached = {}
        latencies = {}
        errors = {}
        for case in cases:
            started = time.perf_counter()
            try:
                cached[case["case_id"]] = rag._hybrid_search(
                    case["question"], [case["library"]] if case["library"] else []
                )
            except Exception as exc:  # 单个 case 失败不应中断整批扫描
                cached[case["case_id"]] = []
                errors[case["case_id"]] = f"{type(exc).__name__}: {exc}"
            latencies[case["case_id"]] = int((time.perf_counter() - started) * 1000)

        for config in group:
            applied = apply_config(app_config, config)
            evidence_top_k = config.get("RERANK_TOP_K", app_config.RERANK_TOP_K)
            rows = evaluate_cached(
                cases,
                cached,
                make_evidence(config, rag._lexical_score),
                k_values,
                "source_heading",
                evidence_top_k=evidence_top_k,
                latencies=latencies,
                errors=errors,
            )
            results.append(
                {
                    "config": config,
                    "retrieval": dict(zip(keys, signature)),
                    "applied": applied,
                    "aggregate": aggregate(rows),
                }
            )
    return results


def _run_dry(cases, configs, k_values):
    cached = {case["case_id"]: [] for case in cases}
    latencies = {case["case_id"]: 0 for case in cases}
    results = []
    for config in configs:
        rows = evaluate_cached(
            cases,
            cached,
            make_evidence(config, lambda question, text: 0.0),
            k_values,
            "source_heading",
            evidence_top_k=config.get("RERANK_TOP_K", 3),
            latencies=latencies,
        )
        results.append({"config": config, "aggregate": aggregate(rows)})
    return results


def _config_columns(results):
    columns = []
    for row in results:
        for key in row["config"]:
            if key not in columns:
                columns.append(key)
    return columns


def _write_csv(path, results, config_columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([*config_columns, *METRIC_KEYS])
        for row in results:
            writer.writerow(
                [
                    *[row["config"].get(key, "") for key in config_columns],
                    *[row["aggregate"].get(key, "") for key in METRIC_KEYS],
                ]
            )


def _print_results(results, k_values):
    hit_key = f"hit@{k_values[0]}"
    ranked = sorted(
        results,
        key=lambda row: (
            row["aggregate"].get("false_answer_rate") or 0,
            -(row["aggregate"].get(hit_key) or 0),
            -(row["aggregate"].get("mrr") or 0),
        ),
    )
    print("\nSWEEP")
    print("=" * 72)
    for row in ranked[:20]:
        config = " ".join(f"{key}={value}" for key, value in row["config"].items())
        aggregate = row["aggregate"]
        print(f"  {config}")
        print(
            f"    hit@{k_values[0]}={aggregate.get(hit_key)} "
            f"recall@5={aggregate.get('recall@5')} mrr={aggregate.get('mrr')} "
            f"false_answer={aggregate.get('false_answer_rate')} "
            f"false_refusal={aggregate.get('false_refusal_rate')}"
        )


def main():
    parser = argparse.ArgumentParser(description="离线检索参数扫描")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--grid", default=str(DEFAULT_GRID))
    parser.add_argument("--k", type=_parse_k, default=(3, 5, 12))
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--include-hard-negatives", action="store_true",
        help="配合 --limit：截断后仍保留全部不可回答样本",
    )
    parser.add_argument("--db-path")
    parser.add_argument("--qdrant-path")
    parser.add_argument("--out", default=str(ROOT / "data" / "eval" / "sweep.json"))
    parser.add_argument("--csv", default=str(ROOT / "data" / "eval" / "sweep.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.db_path:
        os.environ["DB_PATH"] = args.db_path
    if args.qdrant_path:
        os.environ["QDRANT_PATH"] = args.qdrant_path

    spec = _load_spec(args.grid)
    configs = expand_sweep(spec)
    keys = signature_keys(spec)

    all_cases = load_cases(args.dataset)
    cases = all_cases
    if args.limit:
        cases = all_cases[: args.limit]
        if args.include_hard_negatives:
            seen = {case["case_id"] for case in cases}
            cases += [
                case for case in all_cases
                if not case["answerable"] and case["case_id"] not in seen
            ]

    results = (
        _run_dry(cases, configs, args.k)
        if args.dry_run
        else _run_real(cases, configs, keys, spec, args.k)
    )
    results.sort(key=lambda row: json.dumps(row["config"], sort_keys=True))

    payload = {
        "dataset": str(Path(args.dataset).resolve()),
        "k": list(args.k),
        "cases": len(cases),
        "signature_keys": keys,
        "dry_run": args.dry_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "grid": spec,
        "results": results,
    }
    write_json(Path(args.out), payload)
    _write_csv(Path(args.csv), results, _config_columns(results))

    _print_results(results, args.k)
    print(f"\n  json: {args.out}")
    print(f"  csv:  {args.csv}")

    if not args.dry_run:
        try:
            from app import store  # noqa: E402

            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
