"""The Specification model: a named list of requirements, plus validation issue types."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from specguard.models.requirement import Requirement


class Specification(BaseModel):
    """A human-editable set of requirements (the content of `specguard.yml`)."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    name: str = "Untitled specification"
    description: str | None = None
    requirements: list[Requirement] = Field(default_factory=list)

    def enabled_requirements(self) -> list[Requirement]:
        return [r for r in self.requirements if r.enabled]


class ValidationIssue(BaseModel):
    """One problem found while validating a specification."""

    level: Literal["error", "warning"] = "error"
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class SpecificationError(Exception):
    """Raised when a specification cannot be used. Carries every issue found."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        errors = [i for i in issues if i.level == "error"]
        super().__init__(f"Invalid specification ({len(errors)} error(s))")


def format_location(loc: tuple[Any, ...]) -> str:
    """Render a pydantic error location as `requirements[2].severity`."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else str(part)
    return out


def issues_from_pydantic(error: ValidationError) -> list[ValidationIssue]:
    """Turn a pydantic error into short, path-addressed issues."""
    issues: list[ValidationIssue] = []
    for err in error.errors():
        message = err["msg"]
        if err["type"] == "extra_forbidden":
            message = "unknown field (check the spelling)"
        elif err["type"] == "literal_error" and err["loc"] and err["loc"][-1] == "version":
            message = "unsupported version; this release reads `version: 1`"
        issues.append(ValidationIssue(path=format_location(err["loc"]), message=message))
    return issues
