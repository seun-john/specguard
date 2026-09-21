"""Machine-readable JSON report."""

from __future__ import annotations

import json
from typing import Any

from specguard.models.result import AuditReport


def report_to_dict(report: AuditReport) -> dict[str, Any]:
    """The report as plain JSON-compatible data."""
    return report.model_dump(mode="json")


def render_json(report: AuditReport) -> str:
    """Pretty-printed JSON. Non-ASCII text is kept readable rather than escaped."""
    return json.dumps(report_to_dict(report), indent=2, ensure_ascii=False) + "\n"
