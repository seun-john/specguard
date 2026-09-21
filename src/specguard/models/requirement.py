"""The Requirement model: one testable (or deliberately untestable) instruction."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Category(str, Enum):
    """What kind of instruction a requirement expresses."""

    CONTENT = "content"
    STYLE = "style"
    STRUCTURE = "structure"
    COUNT = "count"
    FORMATTING = "formatting"
    TERMINOLOGY = "terminology"
    PRESERVATION = "preservation"
    FILE = "file"
    SEMANTIC = "semantic"
    OTHER = "other"


class Severity(str, Enum):
    """How much a violation matters. `info` violations are reported as warnings."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class VerificationType(str, Enum):
    """How (and whether) SpecGuard can test a requirement.

    deterministic: a built-in checker can decide PASS or FAIL.
    semantic:      needs language understanding; UNVERIFIED unless a semantic verifier is set.
    manual:        needs a human; always UNVERIFIED.
    unsupported:   testable in principle, but no checker exists in this version.
    """

    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"
    MANUAL = "manual"
    UNSUPPORTED = "unsupported"


# Severity weights used by the compliance score. A critical failure costs eight times
# an info-level one. Override per requirement with `weight`.
SEVERITY_WEIGHTS: dict[Severity, float] = {
    Severity.CRITICAL: 8.0,
    Severity.MAJOR: 4.0,
    Severity.MINOR: 2.0,
    Severity.INFO: 1.0,
}

# Highest severity first. Used for thresholds and sorting.
SEVERITY_ORDER: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.MAJOR: 1,
    Severity.MINOR: 2,
    Severity.INFO: 3,
}


class Requirement(BaseModel):
    """A single requirement in a specification.

    If `verification_type` is omitted it is derived: deterministic when a `checker`
    is named, semantic otherwise. Setting it explicitly to a non-deterministic value
    keeps the requirement UNVERIFIED even if a checker is named.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    description: str = Field(min_length=1)
    source_text: str | None = None
    category: Category = Category.OTHER
    severity: Severity = Severity.MAJOR
    verification_type: VerificationType | None = None
    checker: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    weight: float | None = Field(default=None, gt=0)
    enabled: bool = True
    notes: str | None = None

    @model_validator(mode="after")
    def _derive_verification_type(self) -> Requirement:
        if self.verification_type is None:
            self.verification_type = (
                VerificationType.DETERMINISTIC if self.checker else VerificationType.SEMANTIC
            )
        return self

    @property
    def effective_weight(self) -> float:
        """The explicit weight, or the default for this requirement's severity."""
        return self.weight if self.weight is not None else SEVERITY_WEIGHTS[self.severity]

    @property
    def is_deterministic(self) -> bool:
        return self.verification_type is VerificationType.DETERMINISTIC
