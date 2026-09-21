"""Turn an audit entry into the plain lines every report shows.

Terminal, Markdown, JSON-adjacent and SARIF output all need the same facts: what was
required, what was found, where, and what supports the verdict. Building them once
here keeps the reports consistent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from specguard.models.result import AuditEntry, Location, Status
from specguard.utils.text import truncate

MAX_LOCATIONS_SHOWN = 10
MAX_EVIDENCE_SHOWN = 12


@dataclass
class EvidenceView:
    """Presentation-ready facts for one entry."""

    heading: str
    requirement: str
    expected: str | None
    found: str | None
    where: list[str] = field(default_factory=list)
    more_locations: int = 0
    evidence: list[str] = field(default_factory=list)
    reason: str | None = None
    hint: str | None = None
    how_checked: str = ""


def _how_checked(entry: AuditEntry) -> str:
    req = entry.requirement
    if entry.result.checker and entry.result.status is not Status.UNVERIFIED:
        vtype = req.verification_type.value if req.verification_type else ""
        return f"checker `{entry.result.checker}` ({vtype})"
    return f"{req.verification_type.value if req.verification_type else 'unknown'} requirement"


def _where(locations: list[Location]) -> tuple[list[str], int]:
    seen: list[str] = []
    for loc in locations:
        text = loc.describe()
        if text not in seen:
            seen.append(text)
    return seen[:MAX_LOCATIONS_SHOWN], max(0, len(seen) - MAX_LOCATIONS_SHOWN)


def build_view(entry: AuditEntry) -> EvidenceView:
    """Collect the display facts for one entry."""
    result = entry.result
    where, more = _where(result.locations)
    unverified = result.status in (Status.UNVERIFIED, Status.ERROR)
    return EvidenceView(
        heading=f"{result.status.value} {entry.requirement.id}",
        requirement=entry.requirement.source_text or entry.requirement.description,
        expected=result.expected,
        found=result.actual,
        where=where,
        more_locations=more,
        evidence=[truncate(line, 300) for line in result.evidence[:MAX_EVIDENCE_SHOWN]],
        reason=result.message if unverified or result.status is Status.FAIL else None,
        hint=result.remediation_hint,
        how_checked=_how_checked(entry),
    )
