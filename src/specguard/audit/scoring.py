"""Summary metrics: raw counts first, then two separate percentages.

Compliance score
    Weighted share of *verified* requirements that were satisfied. Each requirement
    carries a weight (its `weight`, or a default by severity: critical 8, major 4,
    minor 2, info 1). PASS earns the full weight, WARNING half, FAIL nothing.
    UNVERIFIED and ERROR requirements are left out entirely, so they can never
    raise the score.

Verification coverage
    Verified requirements divided by all enabled requirements: how much of the
    specification was actually tested.

Either value is None (not 100%) when nothing was verified.
"""

from __future__ import annotations

from specguard.models.requirement import VerificationType
from specguard.models.result import AuditEntry, Status, Summary

WARNING_CREDIT = 0.5


def _pct(value: float) -> float:
    return round(value * 100, 1)


def compute_summary(entries: list[AuditEntry], disabled: int = 0) -> Summary:
    """Build the Summary for a list of audit entries."""
    counts = {s.value: 0 for s in Status}
    failed_by_severity = {"critical": 0, "major": 0, "minor": 0, "info": 0}
    for e in entries:
        counts[e.result.status.value] += 1
        if e.result.status in (Status.FAIL, Status.ERROR):
            failed_by_severity[e.requirement.severity.value] += 1

    total = len(entries)
    verified_entries = [e for e in entries if e.result.status.is_verified]
    machine = sum(
        1 for e in entries if e.requirement.verification_type is VerificationType.DETERMINISTIC
    )

    earned = possible = 0.0
    passed = 0
    for e in verified_entries:
        weight = e.requirement.effective_weight
        possible += weight
        if e.result.status is Status.PASS:
            earned += weight
            passed += 1
        elif e.result.status is Status.WARNING:
            earned += weight * WARNING_CREDIT

    return Summary(
        total_requirements=total,
        disabled_requirements=disabled,
        machine_verifiable=machine,
        semantic_or_manual=total - machine,
        counts=counts,
        verified=len(verified_entries),
        failed_by_severity=failed_by_severity,
        compliance_score=_pct(earned / possible) if possible else None,
        unweighted_compliance=_pct(passed / len(verified_entries)) if verified_entries else None,
        verification_coverage=_pct(len(verified_entries) / total) if total else None,
    )
