"""Parameter parsing shared by checkers.

Checkers reject unknown parameter names. A misspelt `maxx: 3000` that was silently
ignored would let a rule pass without testing anything, which is the failure mode
SpecGuard exists to prevent.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from specguard.models.document import Document, TextUnit
from specguard.utils.text import normalize_heading


class ParameterError(ValueError):
    """A rule parameter is missing, has the wrong type, or is not recognised."""


def reject_unknown(params: Mapping[str, Any], allowed: Iterable[str]) -> None:
    """Raise if `params` has a key outside `allowed`, suggesting the closest match."""
    allowed_set = set(allowed)
    for key in params:
        if key not in allowed_set:
            close = difflib.get_close_matches(str(key), sorted(allowed_set), n=1)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            raise ParameterError(f"unknown parameter '{key}'.{hint}")


def get_bool(params: Mapping[str, Any], key: str, default: bool) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise ParameterError(f"'{key}' must be true or false")
    return value


def get_choice(params: Mapping[str, Any], key: str, choices: tuple[str, ...], default: str) -> str:
    value = params.get(key, default)
    if not isinstance(value, str) or value not in choices:
        raise ParameterError(f"'{key}' must be one of: {', '.join(choices)}")
    return value


def get_int(
    params: Mapping[str, Any], key: str, default: int | None = None, minimum: int | None = 0
) -> int | None:
    if key not in params or params[key] is None:
        return default
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParameterError(f"'{key}' must be a whole number")
    if minimum is not None and value < minimum:
        raise ParameterError(f"'{key}' must be at least {minimum}")
    return value


def get_number(params: Mapping[str, Any], key: str) -> float | None:
    if key not in params or params[key] is None:
        return None
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParameterError(f"'{key}' must be a number")
    return float(value)


def get_str_list(
    params: Mapping[str, Any],
    plural_key: str,
    singular_key: str | None = None,
    *,
    required: bool = True,
) -> list[str]:
    """Read `values: [a, b]` or `value: a`. Empty strings are rejected."""
    raw: Any = None
    if plural_key in params:
        raw = params[plural_key]
    elif singular_key and singular_key in params:
        raw = params[singular_key]
    if raw is None:
        if required:
            names = f"'{plural_key}'" + (f" (or '{singular_key}')" if singular_key else "")
            raise ParameterError(f"{names} is required")
        return []
    items = [raw] if isinstance(raw, str) else raw
    if not isinstance(items, list) or not items:
        raise ParameterError(f"'{plural_key}' must be a non-empty list of strings")
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ParameterError(f"'{plural_key}' entries must be non-empty strings")
        result.append(item)
    return result


@dataclass(frozen=True)
class Bounds:
    """An inclusive count range built from `min`/`max`/`exact`/`between` (or their aliases)."""

    minimum: int | None = None
    maximum: int | None = None

    KEYS = ("min", "max", "exact", "between", "at_least", "at_most", "exactly")

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Bounds:
        minimum = _first_int(params, "min", "at_least")
        maximum = _first_int(params, "max", "at_most")
        exact = _first_int(params, "exact", "exactly")
        between = params.get("between")
        if between is not None:
            if (
                not isinstance(between, list)
                or len(between) != 2
                or not all(
                    isinstance(b, int) and not isinstance(b, bool) and b >= 0 for b in between
                )
            ):
                raise ParameterError("'between' must be a list of two whole numbers, e.g. [2, 5]")
            minimum, maximum = between[0], between[1]
        if exact is not None:
            if minimum is not None or maximum is not None:
                raise ParameterError("'exact' cannot be combined with min/max/between")
            minimum = maximum = exact
        if minimum is None and maximum is None:
            raise ParameterError("give at least one of: min, max, exact, between")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ParameterError(f"min ({minimum}) is greater than max ({maximum})")
        return cls(minimum, maximum)

    def contains(self, n: int) -> bool:
        return (self.minimum is None or n >= self.minimum) and (
            self.maximum is None or n <= self.maximum
        )

    def describe(self, noun: str) -> str:
        """`at least 5 words`, `between 2 and 4 words`, `exactly 3 words`."""
        lo, hi = self.minimum, self.maximum
        if lo is not None and hi is not None:
            if lo == hi:
                return f"exactly {lo:,} {noun}"
            return f"between {lo:,} and {hi:,} {noun}"
        if lo is not None:
            return f"at least {lo:,} {noun}"
        assert hi is not None
        return f"at most {hi:,} {noun}"

    def gap(self, n: int) -> str | None:
        """How far `n` is outside the range, e.g. `short by 128` or `over by 5`."""
        if self.minimum is not None and n < self.minimum:
            return f"short by {self.minimum - n:,}"
        if self.maximum is not None and n > self.maximum:
            return f"over by {n - self.maximum:,}"
        return None


def _first_int(params: Mapping[str, Any], *keys: str) -> int | None:
    found = [k for k in keys if params.get(k) is not None]
    if len(found) > 1:
        raise ParameterError(f"use only one of {' / '.join(found)}")
    if not found:
        return None
    return get_int(params, found[0], None, 0)


@dataclass
class Scope:
    """Which parts of the document a text rule looks at."""

    exclude_code_blocks: bool = False
    exclude_sections: list[str] = field(default_factory=list)
    include_headings: bool = True
    include_tables: bool = True

    KEYS = ("exclude_code_blocks", "exclude_sections", "include_headings", "include_tables")

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Scope:
        return cls(
            exclude_code_blocks=get_bool(params, "exclude_code_blocks", False),
            exclude_sections=get_str_list(params, "exclude_sections", required=False),
            include_headings=get_bool(params, "include_headings", True),
            include_tables=get_bool(params, "include_tables", True),
        )

    def select(self, document: Document) -> tuple[list[TextUnit], list[str]]:
        """Units to inspect, plus notes about anything that could not be applied."""
        notes: list[str] = []
        spans: list[tuple[int, int]] = []
        if self.exclude_sections:
            wanted = {normalize_heading(n) for n in self.exclude_sections}
            matched = {h.normalized for h in document.headings if h.normalized in wanted}
            for heading in document.headings:
                if heading.normalized in wanted:
                    spans.append(document.section_span(heading))
            for missing in sorted(wanted - matched):
                notes.append(
                    f'Excluded section "{missing}" was not found; nothing was excluded for it.'
                )
        units = list(
            document.units(
                include_headings=self.include_headings,
                include_tables=self.include_tables,
                exclude_positions=spans,
            )
        )
        if self.exclude_code_blocks:
            units = [u for u in units if u.kind != "code"]
        return units, notes
