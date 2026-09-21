"""Failure thresholds: decide whether an audit should fail a CI job."""

from __future__ import annotations

from specguard.models.requirement import SEVERITY_ORDER, Severity
from specguard.models.result import AuditEntry, AuditReport, Status

FAIL_ON_CHOICES = ("critical", "major", "minor", "any", "none")


def blocking_entries(
    report: AuditReport, fail_on: str = "any", *, fail_on_unverified: bool = False
) -> list[AuditEntry]:
    """Entries that breach the threshold.

    fail_on:
        critical / major / minor  fail (or error) at that severity or worse.
        any                       any FAIL or ERROR. Advisory (`info`) violations are
                                  WARNINGs and never count.
        none                      never fail on results.
    fail_on_unverified: also count UNVERIFIED entries as blocking.

    ERROR results block because an untested requirement cannot be assumed to pass.
    """
    if fail_on not in FAIL_ON_CHOICES:
        raise ValueError(f"fail_on must be one of {', '.join(FAIL_ON_CHOICES)}")
    blocking: list[AuditEntry] = []
    for entry in report.entries:
        status = entry.result.status
        if status is Status.UNVERIFIED:
            if fail_on_unverified:
                blocking.append(entry)
            continue
        if status not in (Status.FAIL, Status.ERROR) or fail_on == "none":
            continue
        if (
            fail_on == "any"
            or SEVERITY_ORDER[entry.requirement.severity] <= SEVERITY_ORDER[Severity(fail_on)]
        ):
            blocking.append(entry)
    return blocking
