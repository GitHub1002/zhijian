"""生成后清理：已有引用和实质内容时去掉追加的拒答句。"""
from app.rag import REFUSAL_ANSWER, _clean_generated_answer


def test_strips_appended_refusal_after_grounded_answer():
    answer = f"二级标题要能单独被检索，例如“年假”“回滚标准”[1][2]。\n\n{REFUSAL_ANSWER}"

    cleaned = _clean_generated_answer(answer)

    assert cleaned == "二级标题要能单独被检索，例如“年假”“回滚标准”[1][2]。"
    assert REFUSAL_ANSWER not in cleaned


def test_keeps_pure_refusal():
    assert _clean_generated_answer(REFUSAL_ANSWER) == REFUSAL_ANSWER


def test_keeps_uncited_answer():
    answer = f"没有引用的回答。\n\n{REFUSAL_ANSWER}"

    assert _clean_generated_answer(answer) == answer
