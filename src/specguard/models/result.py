"""Result models: what a checker returns and what an audit produces."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from specguard.models.requirement import Requirement


class Status(str, Enum):
    """Outcome of one requirement.

    PASS        tested and satisfied.
    FAIL        tested and violated.
    WARNING     tested; not a clear violation, or an advisory (`info`) violation.
    UNVERIFIED  SpecGuard could not test it. This is never a pass.
    ERROR       the checker itself failed, so nothing is known.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    UNVERIFIED = "UNVERIFIED"
    ERROR = "ERROR"

    @property
    def is_verified(self) -> bool:
        """True when the requirement was actually tested."""
        return self in (Status.PASS, Status.FAIL, Status.WARNING)


class Location(BaseModel):
    """Where something was found. Every field is optional; use what the format offers."""

    line: int | None = None
    paragraph: int | None = None
    heading: str | None = None
    table: int | None = None
    row: int | None = None
    column: int | None = None
    excerpt: str | None = None

    def describe(self) -> str:
        """Human-readable position, for example `line 72 (paragraph 14)`."""
        parts: list[str] = []
        if self.table is not None:
            cell = f"table {self.table}"
            if self.row is not None:
                cell += f", row {self.row}"
            if self.column is not None:
                cell += f", column {self.column}"
            parts.append(cell)
        if self.paragraph is not None:
            parts.append(f"paragraph {self.paragraph}")
        if self.line is not None:
            parts.insert(0, f"line {self.line}")
        if not parts and self.heading is not None:
            return f'heading "{self.heading}"'
        text = ", ".join(parts) if parts else "document"
        if self.heading is not None and parts:
            text += f' (under "{self.heading}")'
        return text


class CheckResult(BaseModel):
    """The outcome of running one checker against one requirement."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    status: Status
    message: str
    expected: str | None = None
    actual: str | None = None
    evidence: list[str] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    checker: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    remediation_hint: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AuditEntry(BaseModel):
    """A requirement paired with its result."""

    requirement: Requirement
    result: CheckResult


class DocumentInfo(BaseModel):
    """Facts about the audited document, recorded so a report stands on its own."""

    path: str | None = None
    file_type: str
    size_bytes: int | None = None
    word_count: int
    paragraphs: int
    headings: int
    tables: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class Summary(BaseModel):
    """Counts and scores. Read the raw counts first; the scores are derived from them."""

    total_requirements: int
    disabled_requirements: int = 0
    machine_verifiable: int
    semantic_or_manual: int
    counts: dict[str, int]
    verified: int
    failed_by_severity: dict[str, int]
    # None means nothing was verified, which is not the same as 100%.
    compliance_score: float | None
    unweighted_compliance: float | None
    verification_coverage: float | None


class AuditReport(BaseModel):
    """Everything an audit produced."""

    schema_version: int = 1
    specguard_version: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    specification_name: str
    document: DocumentInfo
    summary: Summary
    entries: list[AuditEntry]
    notices: list[str] = Field(default_factory=list)

    def by_status(self, *statuses: Status) -> list[AuditEntry]:
        wanted = set(statuses)
        return [e for e in self.entries if e.result.status in wanted]
