"""评测集加载与校验。

支持 JSONL（一行一个 case）和 JSON（数组或 {"cases": [...]}）。
`expected_sources` 可以写成 `"source > heading"` 字符串，也可以写成
`{"source": "...", "heading": "..."}` 对象。
"""
import json
from pathlib import Path


def _parse_source(item):
    if isinstance(item, dict):
        return {
            "source": str(item.get("source") or ""),
            "heading": str(item.get("heading") or ""),
        }
    text = str(item or "").strip()
    if " > " in text:
        source, heading = text.split(" > ", 1)
        return {"source": source.strip(), "heading": heading.strip()}
    return {"source": text, "heading": ""}


def normalize_case(row, index=0):
    case = dict(row)
    case.setdefault("case_id", f"case-{index + 1:03d}")
    case["question"] = str(case.get("question") or "").strip()
    case["library"] = str(case.get("library") or "").strip()
    case["expected_sources"] = [
        _parse_source(item) for item in (case.get("expected_sources") or [])
    ]
    case["expected_chunk_ids"] = [
        str(item) for item in (case.get("expected_chunk_ids") or [])
    ]
    case["reference_answer"] = str(case.get("reference_answer") or "")
    case["answerable"] = bool(case.get("answerable", True))
    case["hard_negative"] = bool(case.get("hard_negative", False))
    case["tags"] = list(case.get("tags") or [])
    case["label_source"] = str(case.get("label_source") or "human")
    case["notes"] = str(case.get("notes") or "")
    if not case["question"]:
        raise ValueError(f"{case['case_id']}: question 不能为空")
    return case


def load_cases(path):
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if target.suffix.lower() == ".json":
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("cases", [])
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [normalize_case(row, index) for index, row in enumerate(rows)]
