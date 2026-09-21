"""Compile and run user-supplied regular expressions defensively.

Specifications can come from people (or agents) other than the document owner, so a
pattern is treated as untrusted input:

* the length is capped;
* patterns that can match the empty string are rejected (they "match" everywhere);
* matching runs under the `regex` module's timeout, which stops catastrophic
  backtracking instead of hanging the audit.
"""

from __future__ import annotations

from collections.abc import Iterable

import regex

MAX_PATTERN_LENGTH = 1000
MATCH_TIMEOUT_SECONDS = 2.0

_FLAG_NAMES = {
    "ignorecase": regex.IGNORECASE,
    "multiline": regex.MULTILINE,
    "dotall": regex.DOTALL,
}


class UnsafePatternError(ValueError):
    """The pattern is invalid, too long, or matches the empty string."""


class PatternTimeoutError(RuntimeError):
    """Matching exceeded the time limit."""


def parse_flags(names: Iterable[str]) -> int:
    """Convert flag names (`ignorecase`, `multiline`, `dotall`) to regex flags."""
    flags = 0
    for name in names:
        try:
            flags |= _FLAG_NAMES[name.lower()]
        except KeyError:
            allowed = ", ".join(sorted(_FLAG_NAMES))
            raise UnsafePatternError(f"unknown regex flag {name!r} (allowed: {allowed})") from None
    return flags


def compile_pattern(pattern: str, flags: int = 0) -> regex.Pattern[str]:
    """Compile a pattern or raise UnsafePatternError with a readable reason."""
    if not isinstance(pattern, str) or not pattern:
        raise UnsafePatternError("pattern must be a non-empty string")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise UnsafePatternError(f"pattern is longer than {MAX_PATTERN_LENGTH} characters")
    try:
        compiled = regex.compile(pattern, flags)
    except regex.error as exc:
        raise UnsafePatternError(f"invalid regular expression: {exc}") from exc
    try:
        if compiled.fullmatch("", timeout=MATCH_TIMEOUT_SECONDS) is not None or (
            compiled.search("", timeout=MATCH_TIMEOUT_SECONDS) is not None
        ):
            raise UnsafePatternError(
                "pattern matches the empty string, so it would match everywhere"
            )
    except TimeoutError as exc:  # pragma: no cover - empty input cannot backtrack
        raise UnsafePatternError("pattern could not be evaluated safely") from exc
    return compiled


def finditer_safe(compiled: regex.Pattern[str], text: str) -> list[regex.Match[str]]:
    """All matches in `text`, raising PatternTimeoutError if matching takes too long."""
    try:
        return list(compiled.finditer(text, timeout=MATCH_TIMEOUT_SECONDS))
    except TimeoutError as exc:
        raise PatternTimeoutError(
            "regular expression timed out; it may cause catastrophic backtracking"
        ) from exc
