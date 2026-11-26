"""阈值门禁：识别 RAGAS 报告并按对应指标检查。"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "evals" / "check_thresholds.py"
CONFIG = ROOT / "evals" / "configs" / "thresholds.json"


def _write(path, aggregate):
    path.write_text(json.dumps({"aggregate": aggregate}), encoding="utf-8")
    return str(path)


def _run(tmp_path, candidate):
    baseline = _write(tmp_path / "baseline.json", candidate)
    candidate_path = _write(tmp_path / "candidate.json", candidate)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--baseline", baseline,
         "--candidate", candidate_path, "--config", str(CONFIG)],
        capture_output=True, text=True,
    )


def test_ragas_report_passes_thresholds(tmp_path):
    aggregate = {
        "faithfulness": 0.99,
        "answer_relevancy": 0.93,
        "context_precision": 1.0,
        "context_recall": 0.95,
        "correct_refusal_rate": 1.0,
    }

    result = _run(tmp_path, aggregate)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_ragas_report_rejects_low_faithfulness(tmp_path):
    aggregate = {
        "faithfulness": 0.80,
        "answer_relevancy": 0.93,
        "context_precision": 1.0,
        "context_recall": 0.95,
        "correct_refusal_rate": 1.0,
    }

    result = _run(tmp_path, aggregate)

    assert result.returncode == 1
    assert "faithfulness" in result.stdout


def test_ragas_report_without_negatives_skips_refusal(tmp_path):
    aggregate = {
        "faithfulness": 0.99,
        "answer_relevancy": 0.93,
        "context_precision": 1.0,
        "context_recall": 0.95,
        "correct_refusal_rate": None,
    }

    result = _run(tmp_path, aggregate)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SKIP correct_refusal_rate" in result.stdout
