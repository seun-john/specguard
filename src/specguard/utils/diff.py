"""Word-level diffs and closest-match search, used to explain changed protected text."""

from __future__ import annotations

import difflib
import re

_TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)


def similarity(a: str, b: str) -> float:
    """Similarity in [0, 1] using a cheap upper bound first to skip hopeless pairs."""
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if matcher.real_quick_ratio() < 0.3 or matcher.quick_ratio() < 0.3:
        return 0.0
    return matcher.ratio()


def word_diff(expected: str, found: str) -> str:
    """Show what changed as `[-removed-]{+added+}` inline markup."""
    a = _TOKEN_RE.findall(expected)
    b = _TOKEN_RE.findall(found)
    out: list[str] = []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append("".join(a[a1:a2]))
            continue
        removed = "".join(a[a1:a2]).strip()
        added = "".join(b[b1:b2]).strip()
        if removed:
            out.append(f"[-{removed}-]")
        if added:
            out.append(f"{{+{added}+}}")
        if not removed and not added:
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def sentences(text: str) -> list[tuple[int, str]]:
    """Split text into (offset, sentence) pairs, to find near-matches in long paragraphs."""
    result: list[tuple[int, str]] = []
    start = 0
    for m in re.finditer(r"(?<=[.!?])\s+", text):
        chunk = text[start : m.start()]
        if chunk.strip():
            result.append((start, chunk))
        start = m.end()
    tail = text[start:]
    if tail.strip():
        result.append((start, tail))
    return result
