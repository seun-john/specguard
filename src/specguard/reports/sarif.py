"""SARIF 2.1.0 output for code-scanning and CI integrations.

Only FAIL, ERROR and WARNING entries become SARIF results. UNVERIFIED requirements are
summarised under `run.properties` instead of being reported as findings, because a
requirement that was not tested is not a defect in the document.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from specguard.models.requirement import Severity
from specguard.models.result import AuditEntry, AuditReport, Location, Status

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_VERSION = "2.1.0"

_LEVEL_BY_SEVERITY = {
    Severity.CRITICAL: "error",
    Severity.MAJOR: "error",
    Severity.MINOR: "warning",
    Severity.INFO: "note",
}


def _level(entry: AuditEntry) -> str:
    status = entry.result.status
    if status is Status.ERROR:
        return "error"
    if status is Status.WARNING:
        return "warning"
    return _LEVEL_BY_SEVERITY[entry.requirement.severity]


def _artifact_uri(path: str | None) -> str:
    if not path:
        return "document"
    p = Path(path)
    if p.is_absolute():
        return p.as_uri()
    return quote(p.as_posix(), safe="/:@-._~")


def _location(uri: str, loc: Location | None) -> dict[str, Any]:
    physical: dict[str, Any] = {"artifactLocation": {"uri": uri}}
    result: dict[str, Any] = {"physicalLocation": physical}
    if loc is not None and loc.line is not None:
        region: dict[str, Any] = {"startLine": loc.line}
        if loc.excerpt:
            region["snippet"] = {"text": loc.excerpt}
        physical["region"] = region
    else:
        # Formats without line numbers (DOCX) still need a region for most viewers; the
        # logical location below carries the real position (paragraph, table).
        physical["region"] = {"startLine": 1}
    if loc is not None:
        result["logicalLocations"] = [{"name": loc.describe(), "kind": "member"}]
    return result


def _message(entry: AuditEntry) -> str:
    result = entry.result
    parts = [f"{entry.requirement.description}: {result.message}"]
    if result.expected:
        parts.append(f"Expected: {result.expected}")
    if result.actual:
        parts.append(f"Found: {result.actual}")
    parts.extend(result.evidence[:5])
    return "\n".join(parts)


def report_to_sarif(report: AuditReport) -> dict[str, Any]:
    """Build the SARIF log as a dictionary."""
    uri = _artifact_uri(report.document.path)
    findings = [
        e for e in report.entries if e.result.status in (Status.FAIL, Status.ERROR, Status.WARNING)
    ]

    rules: list[dict[str, Any]] = []
    rule_index: dict[str, int] = {}
    for entry in findings:
        req = entry.requirement
        if req.id in rule_index:
            continue
        rule_index[req.id] = len(rules)
        rules.append(
            {
                "id": req.id,
                "name": req.id,
                "shortDescription": {"text": req.description},
                "fullDescription": {"text": req.source_text or req.description},
                "defaultConfiguration": {"level": _LEVEL_BY_SEVERITY[req.severity]},
                "properties": {
                    "category": req.category.value,
                    "severity": req.severity.value,
                    "verificationType": req.verification_type.value
                    if req.verification_type
                    else None,
                    "checker": req.checker,
                },
            }
        )

    results: list[dict[str, Any]] = []
    for entry in findings:
        result = entry.result
        locations = [_location(uri, loc) for loc in result.locations[:20]] or [_location(uri, None)]
        results.append(
            {
                "ruleId": entry.requirement.id,
                "ruleIndex": rule_index[entry.requirement.id],
                "level": _level(entry),
                "message": {"text": _message(entry)},
                "locations": locations,
                "properties": {
                    "status": result.status.value,
                    "severity": entry.requirement.severity.value,
                    "expected": result.expected,
                    "actual": result.actual,
                    "evidence": result.evidence,
                    "confidence": result.confidence,
                },
            }
        )

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "SpecGuard",
                        "version": report.specguard_version,
                        "rules": rules,
                    }
                },
                "artifacts": [{"location": {"uri": uri}}],
                "results": results,
                "invocations": [{"executionSuccessful": True}],
                "properties": {
                    "specification": report.specification_name,
                    "summary": report.summary.model_dump(mode="json"),
                    "unverifiedRequirements": [
                        e.requirement.id
                        for e in report.entries
                        if e.result.status is Status.UNVERIFIED
                    ],
                },
            }
        ],
    }


def render_sarif(report: AuditReport) -> str:
    return json.dumps(report_to_sarif(report), indent=2, ensure_ascii=False) + "\n"
