"""Code formatting and post-processing (placeholder; expanded later)."""

from __future__ import annotations

import re


def normalize_js_literals(code: str) -> str:
    """Normalize common JS literals/operators into Python equivalents.

    This is a stopgap to keep generated code runnable when models drift.
    """
    def apply_replacements(segment: str) -> str:
        segment = re.sub(r"\bfalse\b", "False", segment)
        segment = re.sub(r"\btrue\b", "True", segment)
        segment = re.sub(r"\bnull\b", "None", segment)
        segment = re.sub(r"\s*&&\s*", " and ", segment)
        segment = re.sub(r"\s*\|\|\s*", " or ", segment)
        segment = re.sub(r"!\s*(?!=)", "not ", segment)  # avoid touching "!="
        return segment

    parts = []
    i = 0
    while i < len(code):
        ch = code[i]
        if ch in ("'", "\""):
            quote = ch
            if code[i : i + 3] == quote * 3:
                end = i + 3
                while end < len(code) and code[end : end + 3] != quote * 3:
                    end += 1
                end = min(len(code), end + 3)
            else:
                end = i + 1
                escape = False
                while end < len(code):
                    if escape:
                        escape = False
                    elif code[end] == "\\":
                        escape = True
                    elif code[end] == quote:
                        end += 1
                        break
                    end += 1
            parts.append(code[i:end])
            i = end
            continue

        next_quote = min(
            [idx for idx in (code.find("'", i), code.find("\"", i)) if idx != -1],
            default=len(code),
        )
        segment = code[i:next_quote]
        parts.append(apply_replacements(segment))
        i = next_quote

    return "".join(parts)
