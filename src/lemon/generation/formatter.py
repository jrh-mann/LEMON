"""Code formatting and post-processing (placeholder; expanded later)."""

from __future__ import annotations

import re


def normalize_js_literals(code: str) -> str:
    """Normalize common JS literals/operators into Python equivalents.

    This is a stopgap to keep generated code runnable when models drift.
    """
    code = re.sub(r"\bfalse\b", "False", code)
    code = re.sub(r"\btrue\b", "True", code)
    code = re.sub(r"\bnull\b", "None", code)
    code = re.sub(r"\s*&&\s*", " and ", code)
    code = re.sub(r"\s*\|\|\s*", " or ", code)
    code = re.sub(r"!([^=\s])", r"not \1", code)  # avoid touching "!="
    code = re.sub(r"!\s+", "not ", code)
    return code


