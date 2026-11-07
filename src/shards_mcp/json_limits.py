"""Interpreter-independent structural limits for untrusted JSON input.

Do not rely on CPython's evolving recursion threshold. This scanner
deliberately ignores delimiter characters inside JSON strings and correctly
tracks escaped quotes and backslashes. The JSON decoder remains responsible
for full syntax validation.
"""
from __future__ import annotations


MAX_JSON_DEPTH = 128


def enforce_json_depth(data: str | bytes, max_depth: int = MAX_JSON_DEPTH) -> None:
    """Reject excessive nesting before parsing or canonicalising untrusted JSON."""
    if type(max_depth) is not int or max_depth < 1:
        raise ValueError("max_depth must be a positive integer")
    depth = 0
    in_string = False
    escaped = False
    for char in data:
        code = char if isinstance(char, int) else ord(char)
        if in_string:
            if escaped:
                escaped = False
            elif code == 92:  # backslash
                escaped = True
            elif code == 34:  # double quote
                in_string = False
            continue
        if code == 34:
            in_string = True
        elif code == 91 or code == 123:  # '[' or '{'
            depth += 1
            if depth > max_depth:
                raise ValueError("JSON nesting limit exceeded")
        elif code == 93 or code == 125:  # ']' or '}'
            depth -= 1
            if depth < 0:
                raise ValueError("malformed JSON nesting")
    if depth != 0 or in_string:
        # json.loads would reject this as well, but return a bounded error
        # even if the interpreter's parser depth threshold changes.
        raise ValueError("malformed JSON structure")
