"""forbidden_regex and required_regex: user-defined patterns, run defensively."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

import regex

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Status
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import (
    ParameterError,
    Scope,
    get_choice,
    get_str_list,
    reject_unknown,
)
from specguard.utils.matching import (
    count_by_key,
    describe_counts,
    find_regex,
    sample_lines,
)
from specguard.utils.safe_regex import (
    PatternTimeoutError,
    UnsafePatternError,
    compile_pattern,
    parse_flags,
)
from specguard.utils.text import plural


@dataclass
class _Config:
    patterns: list[tuple[str, regex.Pattern[str]]]
    require: str
    scope: Scope


def _parse(parameters: Mapping[str, Any]) -> _Config:
    reject_unknown(parameters, ("pattern", "patterns", "flags", "require", *Scope.KEYS))
    sources = get_str_list(parameters, "patterns", "pattern")
    flag_names = get_str_list(parameters, "flags", required=False)
    try:
        flags = parse_flags(flag_names)
        compiled = [(s, compile_pattern(s, flags)) for s in sources]
    except UnsafePatternError as exc:
        raise ParameterError(str(exc)) from exc
    return _Config(
        patterns=compiled,
        require=get_choice(parameters, "require", ("all", "any"), "all"),
        scope=Scope.from_params(parameters),
    )


_HELP = {
    "pattern / patterns": "Regular expression or list of them. Matched inside each paragraph "
    "or table cell. Patterns over 1,000 characters, or matching the empty string, are refused.",
    "flags": "Any of: ignorecase, multiline, dotall.",
    "exclude_code_blocks / exclude_sections": "Skip parts of the document.",
}


@register_rule
class ForbiddenRegexRule(RuleChecker):
    rule_type = "forbidden_regex"
    summary = "No match for any of the regular expressions may appear."
    parameter_help: ClassVar[dict[str, str]] = _HELP

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        return _parse(parameters)

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        try:
            hits = find_regex(units, cfg.patterns)
        except PatternTimeoutError as exc:
            return self.result(requirement, Status.ERROR, str(exc))
        shown = ", ".join(f"/{s}/" for s, _ in cfg.patterns)
        expected = f"No match for: {shown}"
        if not hits:
            return self.passed(
                requirement,
                "No forbidden pattern found.",
                expected=expected,
                actual="0 matches",
                evidence=notes,
            )
        counts = count_by_key(hits)
        return self.failed(
            requirement,
            f"Found {plural(len(hits), 'match', 'matches')} for forbidden pattern.",
            expected=expected,
            actual=plural(len(hits), "match", "matches"),
            evidence=[
                *describe_counts(counts),
                *sample_lines(hits),
                *notes,
            ],
            locations=[h.location for h in hits],
            remediation_hint="Rewrite the matching passages.",
            details={"matches": len(hits)},
        )


@register_rule
class RequiredRegexRule(RuleChecker):
    rule_type = "required_regex"
    summary = "The regular expressions must match somewhere (all of them, or at least one)."
    parameter_help: ClassVar[dict[str, str]] = {**_HELP, "require": "`all` (default) or `any`."}

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        return _parse(parameters)

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        try:
            hits = find_regex(units, cfg.patterns)
        except PatternTimeoutError as exc:
            return self.result(requirement, Status.ERROR, str(exc))
        counts = count_by_key(hits)
        found = [s for s, _ in cfg.patterns if counts.get(s, 0) > 0]
        missing = [s for s, _ in cfg.patterns if counts.get(s, 0) == 0]
        shown = ", ".join(f"/{s}/" for s, _ in cfg.patterns)
        expected = f"{'All' if cfg.require == 'all' else 'At least one'} of: {shown}"
        evidence = [f"/{s}/ matched x {counts[s]}" for s in found]
        evidence += [f"/{s}/ did not match" for s in missing]
        evidence += notes
        ok = not missing if cfg.require == "all" else bool(found)
        if ok:
            first: dict[str, Any] = {}
            for h in hits:
                first.setdefault(h.key, h.location)
            return self.passed(
                requirement,
                "Required pattern found.",
                expected=expected,
                actual=f"{len(found)} of {len(cfg.patterns)} patterns matched",
                evidence=evidence,
                locations=list(first.values()),
            )
        return self.failed(
            requirement,
            "Required pattern not found: " + ", ".join(f"/{s}/" for s in missing) + ".",
            expected=expected,
            actual=f"{len(found)} of {len(cfg.patterns)} patterns matched",
            evidence=evidence,
            remediation_hint="Add text that satisfies the pattern.",
        )
