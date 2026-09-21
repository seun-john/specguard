"""Literal and regex search over text units, returning located hits."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

import regex

from specguard.models.document import TextUnit
from specguard.models.result import Location
from specguard.utils.safe_regex import finditer_safe


@dataclass
class Hit:
    """One match: which value or pattern matched, the matched text, and where."""

    key: str
    matched: str
    location: Location


def literal_pattern(
    values: Iterable[str], *, case_sensitive: bool, whole_word: bool
) -> re.Pattern[str]:
    """One compiled alternation for several literal strings.

    Spaces in a value match any run of whitespace, so a phrase still matches when a
    paragraph is hard-wrapped. Whole-word anchors apply only where the value's edge
    character is a word character (an em dash has no "word" around it).
    """
    parts: list[str] = []
    for value in sorted(set(values), key=len, reverse=True):
        body = re.escape(value).replace("\\ ", r"\s+")
        if whole_word:
            if re.match(r"\w", value[0]):
                body = r"(?<!\w)" + body
            if re.match(r"\w", value[-1]):
                body = body + r"(?!\w)"
        parts.append(body)
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile("|".join(parts), flags)


def find_literals(
    units: Iterable[TextUnit],
    values: list[str],
    *,
    case_sensitive: bool = False,
    whole_word: bool = False,
) -> list[Hit]:
    """Every occurrence of any value in `values`, in document order."""
    pattern = literal_pattern(values, case_sensitive=case_sensitive, whole_word=whole_word)
    canonical = {
        re.sub(r"\s+", " ", v) if case_sensitive else re.sub(r"\s+", " ", v).casefold(): v
        for v in values
    }
    hits: list[Hit] = []
    for unit in units:
        flat = unit.flat
        for m in pattern.finditer(flat):
            text = re.sub(r"\s+", " ", m.group(0))
            key = canonical.get(text if case_sensitive else text.casefold(), m.group(0))
            hits.append(Hit(key, m.group(0), unit.locate(m.start(), m.end())))
    return hits


def find_regex(
    units: Iterable[TextUnit], patterns: list[tuple[str, regex.Pattern[str]]]
) -> list[Hit]:
    """Every match of each (label, compiled pattern) in each unit."""
    hits: list[Hit] = []
    for unit in units:
        for label, compiled in patterns:
            for m in finditer_safe(compiled, unit.text):
                hits.append(Hit(label, m.group(0), unit.locate(m.start(), m.end())))
    hits.sort(key=lambda h: (h.location.paragraph or 0, h.location.line or 0))
    return hits


def count_by_key(hits: list[Hit]) -> Counter[str]:
    return Counter(h.key for h in hits)


def describe_counts(counts: Counter[str], *, limit: int = 12) -> list[str]:
    """`"—" x 7` lines, most frequent first."""
    lines = [f'"{k}" x {v}' for k, v in counts.most_common(limit)]
    if len(counts) > limit:
        lines.append(f"... and {len(counts) - limit} more distinct values")
    return lines


def sample_lines(hits: list[Hit], limit: int = 5) -> list[str]:
    """One `where: excerpt` line per distinct place, for the first few places."""
    seen: set[str] = set()
    lines: list[str] = []
    for h in hits:
        where = h.location.describe()
        if where in seen:
            continue
        seen.add(where)
        lines.append(f"{where}: {h.location.excerpt}")
        if len(lines) == limit:
            break
    return lines


def location_summary(hits: list[Hit], limit: int = 8) -> str:
    """`paragraph 14, paragraph 37 ...` for evidence lines."""
    seen: list[str] = []
    for h in hits:
        label = h.location.describe()
        if label not in seen:
            seen.append(label)
    text = "; ".join(seen[:limit])
    return text + (f"; and {len(seen) - limit} more" if len(seen) > limit else "")
