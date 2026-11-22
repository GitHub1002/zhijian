"""管理端 CSV 导出：公式注入转义。"""
from app.main import _csv_cell


def test_csv_cell_escapes_formula_prefixes():
    assert _csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert _csv_cell("+1") == "'+1"
    assert _csv_cell("-1") == "'-1"
    assert _csv_cell("@sum") == "'@sum"


def test_csv_cell_keeps_numbers_and_none():
    assert _csv_cell(-1.5) == -1.5
    assert _csv_cell(3) == 3
    assert _csv_cell(None) == ""
    assert _csv_cell("普通文本") == "普通文本"
