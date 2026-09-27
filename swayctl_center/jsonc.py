"""JSON with comments and trailing commas (waybar's config.jsonc, often
swaync's too), read-only: we parse users' files, never write them back."""
from __future__ import annotations

import json
from typing import Any


def strip(text: str) -> str:
    """Remove // and /* */ comments and trailing commas outside strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "]}":
            # drop a trailing comma before the closing bracket
            j = len(out) - 1
            while j >= 0 and out[j].isspace():
                j -= 1
            if j >= 0 and out[j] == ",":
                del out[j]
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def loads(text: str) -> Any:
    return json.loads(strip(text))
