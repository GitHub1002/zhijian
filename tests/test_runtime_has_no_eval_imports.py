from pathlib import Path

BANNED = ("ragas", "llama_index", "tru_lens", "pandas")


def test_app_does_not_import_eval_libraries():
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in BANNED:
            if f"import {name}" in text or f"from {name}" in text:
                offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders
