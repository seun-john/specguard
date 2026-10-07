"""Report model and renderers shared by `specguard done` and `specguard context`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from specguard import __version__
from specguard.models.result import CheckResult, Status


class ProjectReport(BaseModel):
    """Findings for one folder. Every finding is a normal SpecGuard CheckResult."""

    schema_version: int = 1
    specguard_version: str = __version__
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    kind: str  # "done", "context" or "scope"
    root: str
    results: list[CheckResult]
    notices: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Status}
        for r in self.results:
            counts[r.status.value] += 1
        return counts

    def failed(self) -> bool:
        return any(r.status in (Status.FAIL, Status.ERROR) for r in self.results)

    def has_unverified(self) -> bool:
        return any(r.status is Status.UNVERIFIED for r in self.results)


def render_project_report(report: ProjectReport, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
    if fmt in ("terminal", "markdown"):
        return _text(report, markdown=fmt == "markdown")
    raise ValueError(f"Unknown format '{fmt}'. Choose from: terminal, json, markdown")


def _text(report: ProjectReport, *, markdown: bool) -> str:
    title = {
        "done": "SPECGUARD DONE-CHECK",
        "context": "SPECGUARD CONTEXT LINT",
        "scope": "SPECGUARD SCOPE FENCE",
    }[report.kind]
    counts = report.counts()
    lines = [f"# {title}" if markdown else title, ""]
    lines.append("  ".join(f"{k}: {v}" for k, v in counts.items() if v))
    lines.append("")
    for r in report.results:
        lines.append(f"{r.status.value:<10} {r.requirement_id}  {r.message}")
        for ev in r.evidence:
            lines.append(f"    {ev}")
        if r.remediation_hint:
            lines.append(f"    Fix: {r.remediation_hint}")
    if not report.results:
        lines.append("No findings.")
    for notice in report.notices:
        lines.extend(["", f"Note: {notice}"])
    return "\n".join(lines) + "\n"
