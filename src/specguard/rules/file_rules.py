"""file_type and docx_format: properties of the file rather than its words."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Status
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import (
    ParameterError,
    get_choice,
    get_number,
    get_str_list,
    reject_unknown,
)


@dataclass
class _TypeConfig:
    extensions: list[str]


@register_rule
class FileTypeRule(RuleChecker):
    rule_type = "file_type"
    summary = "The audited file must have one of the listed types (by extension)."
    parameter_help: ClassVar[dict[str, str]] = {
        "extensions / extension": "Allowed types, e.g. [docx] or [md, txt]."
    }

    def parse(self, parameters: Mapping[str, Any]) -> _TypeConfig:
        reject_unknown(parameters, ("extensions", "extension"))
        raw = get_str_list(parameters, "extensions", "extension")
        return _TypeConfig([e.lower().lstrip(".") for e in raw])

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        if document.path:
            actual = PurePath(document.path).suffix.lower().lstrip(".")
            if not actual:
                actual = document.file_type
        else:
            actual = document.file_type
        expected = "Type: " + " or ".join(f".{e}" for e in cfg.extensions)
        # Accept "markdown" for md and "text" for txt so specs read naturally.
        aliases = {"markdown": "md", "text": "txt"}
        allowed = {aliases.get(e, e) for e in cfg.extensions}
        if actual in allowed or document.file_type in allowed:
            return self.passed(
                requirement,
                f"File type .{actual} is allowed.",
                expected=expected,
                actual=f".{actual}",
            )
        return self.failed(
            requirement,
            f"File type is .{actual}; expected "
            + " or ".join(f".{e}" for e in cfg.extensions)
            + ".",
            expected=expected,
            actual=f".{actual}",
            remediation_hint="Deliver the document in the required format.",
        )


_FORMAT_KEYS = (
    "margin_cm",
    "margins_cm",
    "tolerance_cm",
    "orientation",
    "font_name",
    "font_size_pt",
    "line_spacing",
    "line_spacing_tolerance",
)


@dataclass
class _FormatConfig:
    margins: dict[str, float] = field(default_factory=dict)
    tolerance_cm: float = 0.05
    orientation: str | None = None
    font_name: str | None = None
    font_size_pt: float | None = None
    line_spacing: float | None = None
    line_spacing_tolerance: float = 0.05


@register_rule
class DocxFormatRule(RuleChecker):
    rule_type = "docx_format"
    summary = "Basic Word page setup and default style: margins, orientation, font, line spacing."
    parameter_help: ClassVar[dict[str, str]] = {
        "margin_cm": "All four page margins, in cm.",
        "margins_cm": "Per-side margins: {top, bottom, left, right}, in cm.",
        "tolerance_cm": "Allowed difference for margins (default 0.05).",
        "orientation": "`portrait` or `landscape`.",
        "font_name": "Font of the default (Normal) style.",
        "font_size_pt": "Font size of the default style, in points.",
        "line_spacing": "Line spacing multiple of the default style, e.g. 1.5.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _FormatConfig:
        reject_unknown(parameters, _FORMAT_KEYS)
        cfg = _FormatConfig()
        margin = get_number(parameters, "margin_cm")
        if margin is not None:
            cfg.margins = dict.fromkeys(("top", "bottom", "left", "right"), margin)
        per_side = parameters.get("margins_cm")
        if per_side is not None:
            if not isinstance(per_side, dict) or not set(per_side) <= {
                "top",
                "bottom",
                "left",
                "right",
            }:
                raise ParameterError(
                    "'margins_cm' must be a mapping of top/bottom/left/right to cm"
                )
            for side, value in per_side.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ParameterError(f"'margins_cm.{side}' must be a number")
                cfg.margins[side] = float(value)
        tol = get_number(parameters, "tolerance_cm")
        cfg.tolerance_cm = 0.05 if tol is None else tol
        if "orientation" in parameters:
            cfg.orientation = get_choice(
                parameters, "orientation", ("portrait", "landscape"), "portrait"
            )
        name = parameters.get("font_name")
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise ParameterError("'font_name' must be a non-empty string")
            cfg.font_name = name
        cfg.font_size_pt = get_number(parameters, "font_size_pt")
        cfg.line_spacing = get_number(parameters, "line_spacing")
        ls_tol = get_number(parameters, "line_spacing_tolerance")
        cfg.line_spacing_tolerance = 0.05 if ls_tol is None else ls_tol
        if not (
            cfg.margins or cfg.orientation or cfg.font_name or cfg.font_size_pt or cfg.line_spacing
        ):
            raise ParameterError(
                "give at least one of: margin_cm, margins_cm, orientation, font_name, "
                "font_size_pt, line_spacing"
            )
        return cfg

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        if document.file_type != "docx":
            return self.unverified(
                requirement,
                f"docx_format only applies to .docx files; this is a .{document.file_type} file.",
            )
        meta = document.metadata
        problems: list[str] = []
        unknown: list[str] = []
        ok: list[str] = []

        for i, section in enumerate(meta.get("sections", []), start=1):
            for side, want in cfg.margins.items():
                have = section.get(f"margin_{side}_cm")
                label = f"section {i} {side} margin"
                if have is None:
                    unknown.append(f"{label}: not set")
                elif abs(have - want) > cfg.tolerance_cm:
                    problems.append(f"{label}: {have} cm (required {want} cm)")
                else:
                    ok.append(f"{label}: {have} cm")
            if cfg.orientation:
                have_o = section.get("orientation")
                if have_o != cfg.orientation:
                    problems.append(
                        f"section {i} orientation: {have_o} (required {cfg.orientation})"
                    )
                else:
                    ok.append(f"section {i} orientation: {have_o}")

        def compare(label: str, have: Any, want: Any, tolerance: float | None = None) -> None:
            if have is None:
                unknown.append(
                    f"{label}: not set on the default style (inherited from theme or defaults)"
                )
            elif (
                abs(have - want) > tolerance
                if tolerance is not None
                else str(have).lower() != str(want).lower()
            ):
                problems.append(f"{label}: {have} (required {want})")
            else:
                ok.append(f"{label}: {have}")

        if cfg.font_name:
            compare("default font", meta.get("default_font_name"), cfg.font_name)
        if cfg.font_size_pt:
            compare(
                "default font size (pt)", meta.get("default_font_size_pt"), cfg.font_size_pt, 0.01
            )
        if cfg.line_spacing:
            compare(
                "default line spacing",
                meta.get("default_line_spacing"),
                cfg.line_spacing,
                cfg.line_spacing_tolerance,
            )

        evidence = [*(f"MISMATCH {p}" for p in problems), *(f"UNKNOWN {u}" for u in unknown), *ok]
        if problems:
            return self.failed(
                requirement,
                "Page setup or default style differs from the requirement.",
                expected="See evidence",
                actual="; ".join(problems),
                evidence=evidence,
                remediation_hint="Adjust page setup or the Normal style in Word.",
            )
        if unknown:
            return self.result(
                requirement,
                Status.UNVERIFIED,
                "Some settings could not be read from the file, so they were not verified.",
                evidence=evidence,
                confidence=0.5,
            )
        return self.passed(requirement, "Page setup and default style match.", evidence=evidence)
