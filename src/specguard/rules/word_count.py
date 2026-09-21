"""word_count: minimum, maximum, exact or ranged length."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import Bounds, Scope, get_choice, reject_unknown
from specguard.utils.text import count_words


@dataclass
class _Config:
    bounds: Bounds
    scope: Scope
    method: str


@register_rule
class WordCountRule(RuleChecker):
    rule_type = "word_count"
    summary = "Document length must be at least / at most / exactly N words, or inside a range."
    parameter_help: ClassVar[dict[str, str]] = {
        "min / max / exact / between": "Limits. `between: [1500, 2000]` sets both ends.",
        "count_method": "`words` (default: letters and digits, hyphenated words count once) or "
        "`whitespace` (closer to Microsoft Word).",
        "include_headings": "Count headings (default true).",
        "include_tables": "Count table text (default true).",
        "exclude_sections": "Heading names whose whole section is not counted, e.g. [References].",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(parameters, (*Bounds.KEYS, *Scope.KEYS, "count_method"))
        return _Config(
            bounds=Bounds.from_params(parameters),
            scope=Scope.from_params(parameters),
            method=get_choice(parameters, "count_method", ("words", "whitespace"), "words"),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        count = sum(count_words(u.text, cfg.method) for u in units)
        expected = cfg.bounds.describe("words")
        evidence = [f"Counted {count:,} words ({cfg.method} method)", *notes]
        if cfg.scope.exclude_sections:
            evidence.append("Excluded sections: " + ", ".join(cfg.scope.exclude_sections))
        details = {"word_count": count, "count_method": cfg.method}

        if cfg.bounds.contains(count):
            return self.passed(
                requirement,
                f"Word count is {count:,}, which is {expected}.",
                expected=expected,
                actual=f"{count:,} words",
                evidence=evidence,
                details=details,
            )
        gap = cfg.bounds.gap(count)
        return self.failed(
            requirement,
            f"Word count is {count:,}; required {expected} ({gap}).",
            expected=expected,
            actual=f"{count:,} words ({gap})",
            evidence=evidence,
            remediation_hint="Add content." if gap and gap.startswith("short") else "Trim content.",
            details=details,
        )
