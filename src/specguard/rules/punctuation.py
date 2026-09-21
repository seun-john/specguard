"""forbidden_punctuation: explicitly configured marks may not appear (or only a few times)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import ParameterError, Scope, get_int, get_str_list, reject_unknown
from specguard.utils.matching import (
    count_by_key,
    describe_counts,
    find_literals,
    sample_lines,
)
from specguard.utils.text import plural

# Names users may write instead of the literal character. Nothing is forbidden by default.
NAMED_MARKS: dict[str, list[str]] = {
    "em_dash": ["—"],
    "en_dash": ["–"],
    "semicolon": [";"],
    "exclamation_mark": ["!"],
    "ellipsis": ["…"],
    "colon": [":"],
    "double_hyphen": ["--"],
    "ampersand": ["&"],
    "curly_quotes": ["“", "”", "‘", "’"],
}


def resolve_mark(name: str) -> list[str]:
    """Map `em dash`, `em-dashes`, `em_dash` or a literal character to the characters to search."""
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    for candidate in (key, key.removesuffix("s"), key.removesuffix("es")):
        if candidate in NAMED_MARKS:
            return list(NAMED_MARKS[candidate])
    stripped = name.strip()
    if 0 < len(stripped) <= 3 and not stripped.isalpha():
        return [stripped]
    known = ", ".join(sorted(NAMED_MARKS))
    raise ParameterError(
        f"unknown punctuation '{name}'. Use a literal character or one of: {known}"
    )


@dataclass
class _Config:
    marks: list[str]
    max_allowed: int
    scope: Scope


@register_rule
class ForbiddenPunctuationRule(RuleChecker):
    rule_type = "forbidden_punctuation"
    summary = "Listed punctuation marks may not appear (or only up to `max_allowed` times)."
    parameter_help: ClassVar[dict[str, str]] = {
        "marks": "Names (em_dash, en_dash, semicolon, exclamation_mark, ellipsis, colon, "
        "double_hyphen, ampersand, curly_quotes) or literal characters.",
        "max_allowed": "Total occurrences tolerated across all marks (default 0).",
        "exclude_code_blocks / exclude_sections": "Skip parts of the document.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(parameters, ("marks", "mark", "max_allowed", *Scope.KEYS))
        names = get_str_list(parameters, "marks", "mark")
        marks = [char for name in names for char in resolve_mark(name)]
        return _Config(
            marks=marks,
            max_allowed=get_int(parameters, "max_allowed", 0, 0) or 0,
            scope=Scope.from_params(parameters),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        hits = find_literals(units, cfg.marks, case_sensitive=True, whole_word=False)
        n = len(hits)
        shown = ", ".join(f'"{m}"' for m in cfg.marks)
        allowed = "none" if cfg.max_allowed == 0 else f"at most {cfg.max_allowed}"
        expected = f"{shown}: {allowed} allowed"
        if n <= cfg.max_allowed:
            return self.passed(
                requirement,
                f"Punctuation within the limit ({plural(n, 'occurrence')}).",
                expected=expected,
                actual=plural(n, "occurrence"),
                evidence=notes,
                locations=[h.location for h in hits],
                details={"occurrences": n},
            )
        counts = count_by_key(hits)
        return self.failed(
            requirement,
            f"Found {plural(n, 'occurrence')} of forbidden punctuation"
            + (f" (limit {cfg.max_allowed})." if cfg.max_allowed else "."),
            expected=expected,
            actual=plural(n, "occurrence"),
            evidence=[
                *describe_counts(counts),
                *sample_lines(hits),
                *notes,
            ],
            locations=[h.location for h in hits],
            remediation_hint="Rewrite the sentences without the listed punctuation.",
            details={"occurrences": n, "by_mark": dict(counts)},
        )
