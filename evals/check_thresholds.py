"""对比两次评测结果并执行阈值门禁。回归时退出码非 0。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "evals" / "configs" / "thresholds.json"
LOWER_IS_BETTER = {"false_refusal_rate", "false_answer_rate", "avg_latency_ms"}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="评测阈值门禁")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    baseline = _load(args.baseline).get("aggregate", {})
    candidate = _load(args.candidate).get("aggregate", {})
    config = _load(args.config)
    max_drop = float(config.get("max_drop", 0.02))

    failures = []
    for section in ("retrieval", "ragas"):
        section_thresholds = config.get(section) or {}
        if not any(key in candidate for key in section_thresholds):
            print(f"  SKIP {section}: 本次报告没有这些指标")
            continue
        for key, threshold in section_thresholds.items():
            value = candidate.get(key)
            if value is None:
                failures.append(f"{key}: 缺少指标")
                continue
            if key in LOWER_IS_BETTER:
                if value > threshold:
                    failures.append(f"{key}: {value} > {threshold}")
            elif value < threshold:
                failures.append(f"{key}: {value} < {threshold}")
            old = baseline.get(key)
            if isinstance(old, (int, float)):
                drop = old - value
                if key in LOWER_IS_BETTER:
                    drop = -drop
                if drop > max_drop:
                    failures.append(f"{key}: 比基线下降 {drop:.4f}")

    print("THRESHOLD CHECK")
    print("=" * 24)
    if failures:
        for item in failures:
            print(f"  FAIL {item}")
        sys.exit(1)
    print("  PASS")


if __name__ == "__main__":
    main()
