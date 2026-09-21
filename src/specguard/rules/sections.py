"""required_section: headings that must exist."""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Location
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import ParameterError, get_bool, get_choice, reject_unknown
from specguard.utils.text import normalize_heading


@dataclass
class _Config:
    # Each entry is a group of alternative names; any one satisfies the group.
    groups: list[list[str]]
    require: str
    exact: bool
    case_sensitive: bool


@register_rule
class RequiredSectionRule(RuleChecker):
    rule_type = "required_section"
    summary = "Named headings must exist (Markdown, plain text and Word headings)."
    parameter_help: ClassVar[dict[str, str]] = {
        "headings": "List of required headings. An entry may itself be a list of alternatives, "
        "e.g. `[Introduction, [References, Bibliography]]`.",
        "require": "`all` (default) or `any`.",
        "exact": "Heading text must equal the name, ignoring numbering such as '2.1' and "
        "case (default true). When false, the name may appear inside a longer heading.",
        "case_sensitive": "Compare case exactly (default false).",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(parameters, ("headings", "heading", "require", "exact", "case_sensitive"))
        raw = parameters.get("headings", parameters.get("heading"))
        if raw is None:
            raise ParameterError("'headings' is required")
        entries = [raw] if isinstance(raw, str) else raw
        if not isinstance(entries, list) or not entries:
            raise ParameterError("'headings' must be a non-empty list")
        groups: list[list[str]] = []
        for entry in entries:
            names = [entry] if isinstance(entry, str) else entry
            if (
                not isinstance(names, list)
                or not names
                or not all(isinstance(n, str) and n.strip() for n in names)
            ):
                raise ParameterError(
                    "each heading must be a string or a list of alternative strings"
                )
            groups.append(list(names))
        return _Config(
            groups=groups,
            require=get_choice(parameters, "require", ("all", "any"), "all"),
            exact=get_bool(parameters, "exact", True),
            case_sensitive=get_bool(parameters, "case_sensitive", False),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        fold = not cfg.case_sensitive

        def matches(text: str, name: str) -> bool:
            have = normalize_heading(text, casefold=fold)
            want = normalize_heading(name, casefold=fold)
            return have == want if cfg.exact else want in have

        found: list[tuple[str, str, Location, bool]] = []  # group label, heading, loc, inferred
        missing: list[str] = []
        for group in cfg.groups:
            label = " / ".join(group)
            hit = None
            for h in document.headings:
                if any(matches(h.text, n) for n in group):
                    hit = (
                        label,
                        h.text,
                        Location(line=h.line, paragraph=h.paragraph, heading=h.text),
                        False,
                    )
                    break
            if hit is None:
                # Plain text has no heading markup; accept a standalone short line that
                # reads as a heading, and say so.
                for p in document.paragraphs:
                    if p.heading_candidate and any(matches(p.text, n) for n in group):
                        hit = (
                            label,
                            p.text,
                            Location(line=p.line, paragraph=p.index, heading=p.text),
                            True,
                        )
                        break
            if hit:
                found.append(hit)
            else:
                missing.append(label)

        shown = [" / ".join(g) for g in cfg.groups]
        expected = (
            ("All" if cfg.require == "all" else "Any") + " of these headings: " + ", ".join(shown)
        )
        evidence = []
        for label, heading, loc, inferred in found:
            note = " (a standalone line in plain text, not a formatted heading)" if inferred else ""
            evidence.append(f'Found "{heading}" for {label} at {loc.describe()}{note}')
        evidence += [f"Not found: {m}" for m in missing]
        ok = not missing if cfg.require == "all" else bool(found)
        confidence = 0.8 if any(f[3] for f in found) else 1.0

        if ok:
            return self.passed(
                requirement,
                "Required section(s) present.",
                expected=expected,
                actual="Found: " + ", ".join(f[1] for f in found),
                evidence=evidence,
                locations=[f[2] for f in found],
                confidence=confidence,
                details={"found": [f[0] for f in found], "missing": missing},
            )

        present = [h.text for h in document.headings]
        evidence.append(
            "Headings in document: " + (", ".join(f'"{t}"' for t in present[:15]) or "(none found)")
        )
        hints = []
        for m in missing:
            close = difflib.get_close_matches(
                normalize_heading(m.split(" / ")[0]),
                [normalize_heading(t) for t in present],
                n=1,
                cutoff=0.6,
            )
            if close:
                original = next(t for t in present if normalize_heading(t) == close[0])
                hints.append(f'"{m}" is close to existing heading "{original}"')
        return self.failed(
            requirement,
            "Missing required section(s): " + ", ".join(missing) + ".",
            expected=expected,
            actual="Missing: " + ", ".join(missing),
            evidence=[*evidence, *hints],
            remediation_hint="Add the missing heading(s) using the exact wording required."
            + (
                " Headings must be real headings (Markdown # or Word Heading styles)."
                if document.file_type != "txt"
                else ""
            ),
            details={"found": [f[0] for f in found], "missing": missing},
        )
