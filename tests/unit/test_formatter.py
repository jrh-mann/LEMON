from __future__ import annotations

from src.lemon.generation.formatter import normalize_js_literals


def test_normalize_js_literals_skips_string_literals():
    code = (
        'flag = true && false\n'
        'text = "true && false"\n'
        "other = '!x'\n"
        "neg = !flag\n"
    )
    normalized = normalize_js_literals(code)
    assert 'flag = True and False' in normalized
    assert 'text = "true && false"' in normalized
    assert "other = '!x'" in normalized
    assert "neg = not flag" in normalized
