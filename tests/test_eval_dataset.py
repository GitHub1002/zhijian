"""Golden set 规模和负样本门禁。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    path = ROOT / "evals" / "datasets" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_seed_v1_is_frozen():
    rows = _load("seed_v1.jsonl")

    assert len(rows) == 55
    assert sum(1 for row in rows if not row["answerable"]) == 5


def test_seed_v2_has_ten_hard_negatives():
    rows = _load("seed_v2.jsonl")
    negative = [row for row in rows if not row["answerable"]]

    assert len(rows) == 60
    assert len(negative) == 10
    assert all(row["hard_negative"] for row in negative)
    assert all(not row["expected_sources"] for row in negative)
    assert len({row["case_id"] for row in rows}) == len(rows)
