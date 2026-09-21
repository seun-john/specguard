"""forbidden_text: listed strings must not appear."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import Scope, get_bool, get_str_list, reject_unknown
from specguard.utils.matching import (
    count_by_key,
    describe_counts,
    find_literals,
    sample_lines,
)
from specguard.utils.text import plural


@dataclass
class _Config:
    values: list[str]
    case_sensitive: bool
    whole_word: bool
    scope: Scope


@register_rule
class ForbiddenTextRule(RuleChecker):
    rule_type = "forbidden_text"
    summary = "None of the listed words or phrases may appear."
    parameter_help: ClassVar[dict[str, str]] = {
        "values / value": "String or list of strings that must not appear.",
        "case_sensitive": "Match case exactly (default false).",
        "whole_word": "Only match whole words, so 'art' does not match 'article' (default false).",
        "exclude_code_blocks / exclude_sections": "Skip parts of the document.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(parameters, ("values", "value", "case_sensitive", "whole_word", *Scope.KEYS))
        return _Config(
            values=get_str_list(parameters, "values", "value"),
            case_sensitive=get_bool(parameters, "case_sensitive", False),
            whole_word=get_bool(parameters, "whole_word", False),
            scope=Scope.from_params(parameters),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        hits = find_literals(
            units, cfg.values, case_sensitive=cfg.case_sensitive, whole_word=cfg.whole_word
        )
        shown = ", ".join(f'"{v}"' for v in cfg.values)
        expected = f"None of: {shown}"
        if not hits:
            return self.passed(
                requirement,
                "No forbidden text found.",
                expected=expected,
                actual="0 occurrences",
                evidence=notes,
                details={"occurrences": 0},
            )
        counts = count_by_key(hits)
        return self.failed(
            requirement,
            f"Found {plural(len(hits), 'occurrence')} of forbidden text.",
            expected=expected,
            actual=f"{plural(len(hits), 'occurrence')}",
            evidence=[
                *describe_counts(counts),
                *sample_lines(hits),
                *notes,
            ],
            locations=[h.location for h in hits],
            remediation_hint="Remove or rewrite each listed passage.",
            details={"occurrences": len(hits), "by_value": dict(counts)},
        )
