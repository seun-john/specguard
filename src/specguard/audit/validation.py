"""Specification loading and validation.

Validation happens in layers so the user sees every problem at once:
YAML syntax, then structure (pydantic), then meaning (known checkers, valid parameters,
unique ids).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from specguard.errors import FileAccessError
from specguard.models.requirement import VerificationType
from specguard.models.specification import (
    Specification,
    SpecificationError,
    ValidationIssue,
    issues_from_pydantic,
)
from specguard.rules.base import AuditContext, RuleRegistry, default_registry
from specguard.utils.paths import MAX_SPEC_BYTES, decode_text, read_bytes_limited
from specguard.utils.yamlio import YamlLoadError, load_yaml_text


@dataclass
class ValidationResult:
    """Outcome of validating a specification. `spec` is set when the structure parsed."""

    spec: Specification | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.errors


def check_requirements(
    spec: Specification,
    *,
    base_dir: Path | None = None,
    registry: RuleRegistry | None = None,
) -> list[ValidationIssue]:
    """Semantic checks on a structurally valid specification."""
    reg = registry or default_registry
    context = AuditContext(base_dir=base_dir)
    issues: list[ValidationIssue] = []

    if not spec.requirements:
        issues.append(
            ValidationIssue(level="error", path="requirements", message="no requirements defined")
        )
    if spec.requirements and not spec.enabled_requirements():
        issues.append(
            ValidationIssue(
                level="warning", path="requirements", message="every requirement is disabled"
            )
        )

    seen: dict[str, int] = {}
    for i, req in enumerate(spec.requirements):
        where = f"requirements[{i}] ({req.id})"
        if req.id in seen:
            issues.append(
                ValidationIssue(
                    path=where,
                    message=f"duplicate id '{req.id}' (also used by requirements[{seen[req.id]}])",
                )
            )
        seen.setdefault(req.id, i)

        if req.verification_type is VerificationType.DETERMINISTIC and not req.checker:
            issues.append(
                ValidationIssue(
                    path=f"{where}.checker",
                    message="a deterministic requirement needs a checker; name one, or set "
                    "verification_type to semantic, manual or unsupported",
                )
            )
            continue
        if not req.checker:
            continue
        if reg.get(req.checker) is None:
            close = difflib.get_close_matches(req.checker, reg.names(), n=1)
            hint = (
                f" Did you mean '{close[0]}'?"
                if close
                else f" Known checkers: {', '.join(reg.names())}"
            )
            issues.append(
                ValidationIssue(
                    path=f"{where}.checker", message=f"unknown checker '{req.checker}'.{hint}"
                )
            )
            continue
        if req.verification_type is not VerificationType.DETERMINISTIC:
            issues.append(
                ValidationIssue(
                    level="warning",
                    path=f"{where}.checker",
                    message=f"checker '{req.checker}' is ignored because verification_type is "
                    f"'{req.verification_type.value if req.verification_type else ''}'",
                )
            )
            continue
        checker = reg.create(req.checker, context)
        for problem in checker.validate_parameters(req.parameters):
            issues.append(ValidationIssue(path=f"{where}.parameters", message=problem))
    return issues


def validate_specification_data(
    data: Any,
    *,
    base_dir: Path | None = None,
    registry: RuleRegistry | None = None,
) -> ValidationResult:
    """Validate an already-parsed specification mapping (YAML content or MCP input)."""
    if not isinstance(data, dict):
        return ValidationResult(
            issues=[
                ValidationIssue(
                    path="",
                    message="the specification must be a mapping with a 'requirements' list",
                )
            ]
        )
    try:
        spec = Specification.model_validate(data)
    except ValidationError as exc:
        return ValidationResult(issues=issues_from_pydantic(exc))
    return ValidationResult(
        spec=spec, issues=check_requirements(spec, base_dir=base_dir, registry=registry)
    )


def parse_specification(
    data: Any, *, base_dir: Path | None = None, registry: RuleRegistry | None = None
) -> Specification:
    """Validate and return a Specification, or raise SpecificationError with every issue."""
    result = validate_specification_data(data, base_dir=base_dir, registry=registry)
    if not result.ok or result.spec is None:
        raise SpecificationError(result.issues)
    return result.spec


def validate_specification_file(
    path: str | Path, *, registry: RuleRegistry | None = None
) -> ValidationResult:
    """Read a YAML specification file and validate it. Raises FileAccessError if unreadable."""
    p = Path(path)
    text, _ = decode_text(read_bytes_limited(p, MAX_SPEC_BYTES), str(p))
    try:
        data = load_yaml_text(text)
    except YamlLoadError as exc:
        return ValidationResult(issues=[ValidationIssue(path="", message=f"invalid YAML: {exc}")])
    if data is None:
        return ValidationResult(issues=[ValidationIssue(path="", message="the file is empty")])
    return validate_specification_data(data, base_dir=p.resolve().parent, registry=registry)


def load_specification(
    path: str | Path, *, registry: RuleRegistry | None = None
) -> tuple[Specification, Path]:
    """Load a specification file. Returns (spec, base directory for relative file parameters).

    Raises FileAccessError if the file cannot be read and SpecificationError if it is invalid.
    """
    p = Path(path)
    result = validate_specification_file(p, registry=registry)
    if not result.ok or result.spec is None:
        raise SpecificationError(result.issues)
    return result.spec, p.resolve().parent


__all__ = [
    "FileAccessError",
    "ValidationResult",
    "check_requirements",
    "load_specification",
    "parse_specification",
    "validate_specification_data",
    "validate_specification_file",
]
