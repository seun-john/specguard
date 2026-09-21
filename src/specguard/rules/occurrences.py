"""occurrences and element_count: bounded counts of text matches or structural elements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

import regex

from specguard.models.document import Document, Paragraph
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Location, Status
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import (
    Bounds,
    ParameterError,
    Scope,
    get_bool,
    get_choice,
    get_int,
    get_str_list,
    reject_unknown,
)
from specguard.utils.matching import find_literals, find_regex, sample_lines
from specguard.utils.safe_regex import (
    PatternTimeoutError,
    UnsafePatternError,
    compile_pattern,
    parse_flags,
)
from specguard.utils.text import plural, truncate


@dataclass
class _OccConfig:
    text: str | None
    pattern: tuple[str, regex.Pattern[str]] | None
    bounds: Bounds
    case_sensitive: bool
    whole_word: bool
    scope: Scope


@register_rule
class OccurrenceRule(RuleChecker):
    rule_type = "occurrences"
    summary = "A word, phrase or regex must occur exactly / at least / at most N times."
    parameter_help: ClassVar[dict[str, str]] = {
        "text": "Literal word or phrase to count. Use this or `pattern`.",
        "pattern": "Regular expression to count matches of.",
        "min / max / exact / between": "Allowed number of occurrences (`at_least`, `at_most`, "
        "`exactly` also work).",
        "case_sensitive / whole_word": "Literal matching options (defaults false).",
        "flags": "Regex flags for `pattern`: ignorecase, multiline, dotall.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _OccConfig:
        reject_unknown(
            parameters,
            ("text", "pattern", "flags", "case_sensitive", "whole_word", *Bounds.KEYS, *Scope.KEYS),
        )
        has_text, has_pattern = "text" in parameters, "pattern" in parameters
        if has_text == has_pattern:
            raise ParameterError("give exactly one of 'text' or 'pattern'")
        text = None
        pattern = None
        if has_text:
            text = parameters["text"]
            if not isinstance(text, str) or not text.strip():
                raise ParameterError("'text' must be a single non-empty string")
        else:
            src = parameters["pattern"]
            if not isinstance(src, str):
                raise ParameterError("'pattern' must be a single string")
            try:
                flags = parse_flags(get_str_list(parameters, "flags", required=False))
                pattern = (src, compile_pattern(src, flags))
            except UnsafePatternError as exc:
                raise ParameterError(str(exc)) from exc
        return _OccConfig(
            text=text,
            pattern=pattern,
            bounds=Bounds.from_params(parameters),
            case_sensitive=get_bool(parameters, "case_sensitive", False),
            whole_word=get_bool(parameters, "whole_word", False),
            scope=Scope.from_params(parameters),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        units, notes = cfg.scope.select(document)
        try:
            if cfg.text is not None:
                hits = find_literals(
                    units, [cfg.text], case_sensitive=cfg.case_sensitive, whole_word=cfg.whole_word
                )
                label = f'"{cfg.text}"'
            else:
                assert cfg.pattern is not None
                hits = find_regex(units, [cfg.pattern])
                label = f"/{cfg.pattern[0]}/"
        except PatternTimeoutError as exc:
            return self.result(requirement, Status.ERROR, str(exc))
        n = len(hits)
        expected = f"{label}: {cfg.bounds.describe('occurrences')}"
        evidence = [f"{label} occurs {plural(n, 'time')}", *sample_lines(hits), *notes]
        locations = [h.location for h in hits]
        if cfg.bounds.contains(n):
            return self.passed(
                requirement,
                f"{label} occurs {plural(n, 'time')}, as required.",
                expected=expected,
                actual=plural(n, "occurrence"),
                evidence=evidence,
                locations=locations,
                details={"occurrences": n},
            )
        gap = cfg.bounds.gap(n)
        return self.failed(
            requirement,
            f"{label} occurs {plural(n, 'time')}; required {cfg.bounds.describe('times')} ({gap}).",
            expected=expected,
            actual=f"{plural(n, 'occurrence')} ({gap})",
            evidence=evidence,
            locations=locations,
            remediation_hint="Add occurrences."
            if gap and gap.startswith("short")
            else "Remove occurrences.",
            details={"occurrences": n},
        )


_ELEMENTS = (
    "bullets",
    "numbered_items",
    "list_items",
    "headings",
    "tables",
    "code_blocks",
    "paragraphs",
    "references",
)
_DEFAULT_REFERENCE_HEADINGS = ["References", "Reference list", "Bibliography", "Works cited"]


@dataclass
class _ElemConfig:
    element: str
    bounds: Bounds
    level: int | None
    section_names: list[str]


@register_rule
class ElementCountRule(RuleChecker):
    rule_type = "element_count"
    summary = "Count structural elements (bullets, headings, tables, code blocks, references...)."
    parameter_help: ClassVar[dict[str, str]] = {
        "element": "One of: " + ", ".join(_ELEMENTS) + ".",
        "min / max / exact / between": "Allowed count.",
        "level": "For `headings`: only count headings of this level.",
        "section_names": "For `references`: heading names that mark the reference list "
        "(default: References, Reference list, Bibliography, Works cited).",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _ElemConfig:
        reject_unknown(parameters, ("element", "level", "section_names", *Bounds.KEYS))
        if "element" not in parameters:
            raise ParameterError("'element' is required")
        return _ElemConfig(
            element=get_choice(parameters, "element", _ELEMENTS, _ELEMENTS[0]),
            bounds=Bounds.from_params(parameters),
            level=get_int(parameters, "level", None, 1),
            section_names=get_str_list(parameters, "section_names", required=False)
            or _DEFAULT_REFERENCE_HEADINGS,
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        items, notes, confidence = self._collect(document, cfg)
        n = len(items)
        noun = cfg.element.replace("_", " ")
        expected = cfg.bounds.describe(noun)
        evidence = [f"Counted {n:,} {noun}", *notes]
        if cfg.element == "tables":
            locations = [Location(line=p.line, table=p.index) for p in items]
        else:
            locations = [
                Location(line=p.line, paragraph=p.index, excerpt=truncate(p.text, 80))
                for p in items
            ]
        if cfg.bounds.contains(n):
            return self.passed(
                requirement,
                f"Found {n:,} {noun}, as required.",
                expected=expected,
                actual=f"{n:,} {noun}",
                evidence=evidence,
                locations=locations,
                confidence=confidence,
                details={"count": n},
            )
        gap = cfg.bounds.gap(n)
        return self.failed(
            requirement,
            f"Found {n:,} {noun}; required {expected} ({gap}).",
            expected=expected,
            actual=f"{n:,} {noun} ({gap})",
            evidence=evidence,
            locations=locations,
            confidence=confidence,
            remediation_hint="Add more." if gap and gap.startswith("short") else "Remove some.",
            details={"count": n},
        )

    @staticmethod
    def _collect(document: Document, cfg: _ElemConfig) -> tuple[list[Paragraph], list[str], float]:
        notes: list[str] = []
        confidence = 1.0
        el = cfg.element
        paragraphs = document.paragraphs
        if el == "bullets":
            items = [p for p in paragraphs if p.list_marker == "bullet"]
        elif el == "numbered_items":
            items = [p for p in paragraphs if p.list_marker == "numbered"]
        elif el == "list_items":
            items = [p for p in paragraphs if p.list_marker is not None]
        elif el == "headings":
            wanted = {h.paragraph for h in document.headings if cfg.level in (None, h.level)}
            items = [p for p in paragraphs if p.index in wanted and p.kind == "heading"]
        elif el == "code_blocks":
            items = document.code_blocks
        elif el == "paragraphs":
            items = [p for p in paragraphs if p.kind in ("paragraph", "quote") and p.text.strip()]
        elif el == "tables":
            # Tables are not paragraphs; a stand-in per table keeps location reporting uniform.
            items = [
                Paragraph(index=t.index, text=f"table {t.index}", position=t.position, line=t.line)
                for t in document.tables
            ]
        else:  # references
            confidence = 0.8
            headings = document.find_headings(cfg.section_names, exact=True)
            if not headings:
                notes.append(
                    "No reference-list heading found (looked for: "
                    + ", ".join(cfg.section_names)
                    + ")"
                )
                items = []
            else:
                items = [p for p in document.body_paragraphs_under(headings[0]) if p.kind != "code"]
                notes.append(
                    f'Counted entries under "{headings[0].text}": one per paragraph or list item. '
                    "References run together in one paragraph are counted as one."
                )
        return items, notes, confidence
