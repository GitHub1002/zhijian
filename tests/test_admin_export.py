"""管理端 CSV 导出：公式注入转义和 PII 脱敏。"""
from fastapi.testclient import TestClient

from app import db
from app.main import _csv_cell, _redact_pii, app


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


def test_redact_pii_patterns():
    text = "邮箱 a.b@example.com，手机 13800138000，身份证 110101199001011234"

    result = _redact_pii(text)

    assert "[email]" in result
    assert "[phone]" in result
    assert "[id]" in result
    assert "a.b@example.com" not in result
    assert "13800138000" not in result
    assert "110101199001011234" not in result


def test_export_redacts_pii_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.create_user("admin", "secret123", role="admin")
    user = db.create_user("alice", "secret123")
    answer_id = db.create_answer(user["id"], "问题", "回答", "[]")
    db.save_feedback(
        answer_id,
        user["id"],
        1,
        sentiment="negative",
        reasons=["wrong_info"],
        comment="联系 a@b.com 或 13800138000，身份证 110101199001011234",
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "secret123"}
    ).status_code == 200

    redacted = client.get("/api/admin/feedback/export.csv").text
    assert "[email]" in redacted
    assert "[phone]" in redacted
    assert "[id]" in redacted
    assert "a@b.com" not in redacted

    raw = client.get("/api/admin/feedback/export.csv?redact_pii=false").text
    assert "a@b.com" in raw
    assert "13800138000" in raw
