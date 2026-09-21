"""required_text: listed strings must appear."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Location
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import Scope, get_bool, get_choice, get_str_list, reject_unknown
from specguard.utils.matching import count_by_key, find_literals


@dataclass
class _Config:
    values: list[str]
    require: str
    case_sensitive: bool
    whole_word: bool
    scope: Scope


@register_rule
class RequiredTextRule(RuleChecker):
    rule_type = "required_text"
    summary = "Listed words or phrases must appear (all of them, or at least one)."
    parameter_help: ClassVar[dict[str, str]] = {
        "values / value": "String or list of strings that must appear.",
        "require": "`all` (default) or `any`.",
        "case_sensitive": "Match case exactly (default false).",
        "whole_word": "Only match whole words (default false).",
        "exclude_code_blocks / exclude_sections": "Skip parts of the document.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(
            parameters, ("values", "value", "require", "case_sensitive", "whole_word", *Scope.KEYS)
        )
        return _Config(
            values=get_str_list(parameters, "values", "value"),
            require=get_choice(parameters, "require", ("all", "any"), "all"),
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
        counts = count_by_key(hits)
        found = [v for v in cfg.values if counts.get(v, 0) > 0]
        missing = [v for v in cfg.values if counts.get(v, 0) == 0]
        quoted = ", ".join(f'"{v}"' for v in cfg.values)
        expected = f"{'All' if cfg.require == 'all' else 'At least one'} of: {quoted}"
        evidence = [f'"{v}" found x {counts[v]}' for v in found]
        evidence += [f'"{v}" not found' for v in missing]
        evidence += notes
        first_hits: dict[str, Location] = {}
        for h in hits:
            first_hits.setdefault(h.key, h.location)
        ok = not missing if cfg.require == "all" else bool(found)

        if ok:
            return self.passed(
                requirement,
                "Required text found.",
                expected=expected,
                actual="Found: " + ", ".join(f'"{v}"' for v in found),
                evidence=evidence,
                locations=list(first_hits.values()),
                details={"found": found, "missing": missing},
            )
        return self.failed(
            requirement,
            "Required text not found: " + ", ".join(f'"{v}"' for v in missing) + ".",
            expected=expected,
            actual="Missing: " + ", ".join(f'"{v}"' for v in missing),
            evidence=evidence,
            remediation_hint="Add the missing text where it belongs.",
            details={"found": found, "missing": missing},
        )
