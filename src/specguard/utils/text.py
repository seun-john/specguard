"""Small text helpers shared by extractors and rules."""

from __future__ import annotations

import re

# A word is a run of letters/digits that may contain inner hyphens or apostrophes
# ("well-known", "don't"), or a number with separators ("1,500", "3.14").
# Markdown markers and stray punctuation such as "—" are not words.
_WORD_RE = re.compile(r"\d+(?:[.,]\d+)+|[^\W_]+(?:['’\-][^\W_]+)*")

_NUMBERING_RE = re.compile(
    r"^(?:(?:chapter|section|part)\s+(?:\d+|[ivxlc]+)\s*[:.\-–—]?\s*|\d+(?:\.\d+)*[.)]?\s+|[ivxlc]+[.)]\s+)",
    re.IGNORECASE,
)


def count_words(text: str, method: str = "words") -> int:
    """Count words.

    method="words" counts word tokens as described above.
    method="whitespace" counts whitespace-separated chunks, which is closer to what
    Microsoft Word reports (it counts a lone "—" as a word).
    """
    if method == "whitespace":
        return len(text.split())
    return len(_WORD_RE.findall(text))


def collapse_whitespace(text: str) -> str:
    """Replace every run of whitespace with a single space."""
    return re.sub(r"\s+", " ", text).strip()


def normalize_heading(text: str, *, casefold: bool = True) -> str:
    """Reduce a heading to a comparable form.

    Drops emphasis markers, leading numbering ("2.1", "Chapter 3:"), a trailing colon
    or full stop, extra whitespace, and (unless `casefold` is False) case.
    """
    cleaned = re.sub(r"^#+\s*|\s*#+$", "", text.strip())
    cleaned = re.sub(r"[*_`]", "", cleaned)
    cleaned = collapse_whitespace(cleaned)
    cleaned = _NUMBERING_RE.sub("", cleaned, count=1)
    cleaned = cleaned.rstrip(":.").strip()
    return cleaned.casefold() if casefold else cleaned


def make_excerpt(text: str, start: int, end: int, width: int = 40) -> str:
    """A short single-line snippet around [start, end) with ellipses when trimmed."""
    lo = max(0, start - width)
    hi = min(len(text), end + width)
    snippet = collapse_whitespace(text[lo:hi])
    return f"{'…' if lo > 0 else ''}{snippet}{'…' if hi < len(text) else ''}"


def truncate(text: str, limit: int = 200) -> str:
    """Shorten text for display, keeping it on one line."""
    flat = collapse_whitespace(text)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """`plural(1, "word")` -> "1 word"; `plural(2, "word")` -> "2 words"."""
    word = singular if n == 1 else (plural_form or singular + "s")
    return f"{n:,} {word}"
