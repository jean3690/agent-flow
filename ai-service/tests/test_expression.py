import pytest

from app.core.errors import FlowValidationError
from app.core.expression import evaluate, truthy
from app.core.template import build_names, render


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("outputs.a.text == 'hi'", True),
        ("'x' in ['x', 'y']", True),
        ("len(items) > 2", True),
        ("not flag", True),
        ("score >= 60 and score < 90", True),
    ],
)
def test_evaluate_basic(expression, expected):
    names = {
        "outputs": {"a": {"text": "hi"}},
        "items": [1, 2, 3],
        "flag": False,
        "score": 75,
    }
    assert evaluate(expression, names) == expected


def test_attribute_on_missing_dict_key_is_none():
    assert evaluate("outputs.missing.text", {"outputs": {}}) is None


def test_private_attribute_blocked():
    with pytest.raises(FlowValidationError):
        evaluate("outputs.__class__", {"outputs": {}})


def test_import_blocked():
    with pytest.raises(FlowValidationError):
        evaluate("__import__('os').system('ls')", {})


def test_truthy_strings():
    assert truthy("false") is False
    assert truthy("0") is False
    assert truthy("hello") is True


def test_render_template():
    names = build_names({"topic": "LangGraph"}, {}, {"llm1": {"text": "结果"}})
    assert render("主题：{{topic}}，结果：{{llm1.text}}", names) == "主题：LangGraph，结果：结果"
    assert render("缺失：{{nope}}", names) == "缺失：[nope: 未知变量: nope]"
