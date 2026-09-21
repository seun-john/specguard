"""Human-readable terminal report, drawn with Rich."""

from __future__ import annotations

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from specguard.audit.evidence import EvidenceView, build_view
from specguard.models.requirement import SEVERITY_ORDER
from specguard.models.result import AuditEntry, AuditReport, Status

STATUS_STYLE = {
    Status.PASS: "bold green",
    Status.FAIL: "bold red",
    Status.WARNING: "bold yellow",
    Status.UNVERIFIED: "bold cyan",
    Status.ERROR: "bold magenta",
}


def _pct(value: float | None) -> str:
    return "n/a (nothing was verified)" if value is None else f"{value:g}%"


def _field(console: Console, label: str, value: str, style: str = "") -> None:
    line = Text("  ")
    line.append(f"{label}: ", style="dim")
    line.append(value, style=style)
    console.print(line)


def _print_entry(console: Console, entry: AuditEntry, view: EvidenceView) -> None:
    status = entry.result.status
    head = Text()
    head.append(view.heading, style=STATUS_STYLE[status])
    head.append(f"  [{entry.requirement.severity.value}]", style="dim")
    console.print(head)
    _field(console, "Requirement", view.requirement)
    if status in (Status.UNVERIFIED, Status.ERROR):
        _field(console, "Reason", view.reason or entry.result.message)
    else:
        if view.expected:
            _field(console, "Expected", view.expected)
        if view.found:
            _field(console, "Found", view.found, "bold" if status is Status.FAIL else "")
        if view.reason and status is Status.FAIL:
            _field(console, "Result", view.reason)
    if view.where:
        more = f" (+{view.more_locations} more)" if view.more_locations else ""
        _field(console, "Location", "; ".join(view.where) + more)
    if view.evidence:
        console.print(Text("  Evidence:", style="dim"))
        for line in view.evidence:
            console.print(Text(f"    - {line}"))
    if view.hint and status is Status.FAIL:
        _field(console, "Suggestion", view.hint)
    _field(console, "Checked by", view.how_checked, "dim")
    console.print()


def render_terminal(report: AuditReport, console: Console, *, verbose: bool = False) -> None:
    """Print the audit report. `verbose` also prints the evidence for passing requirements."""
    s = report.summary
    console.print(Text("SPECGUARD AUDIT", style="bold"))
    console.print(Rule(style="dim"))
    _field(console, "File", report.document.path or "(in-memory text)")
    _field(console, "Specification", report.specification_name)
    _field(
        console,
        "Document",
        f"{report.document.word_count:,} words, {report.document.paragraphs} paragraphs, "
        f"{report.document.headings} headings, {report.document.tables} tables",
    )
    _field(console, "Requirements", str(s.total_requirements))
    console.print()
    for status in Status:
        n = s.counts.get(status.value, 0)
        if n or status in (Status.PASS, Status.FAIL, Status.UNVERIFIED):
            line = Text("  ")
            line.append(f"{status.value:<11}", style=STATUS_STYLE[status])
            line.append(f"{n:>3}")
            console.print(line)
    console.print()
    _field(console, "Compliance among verified requirements", _pct(s.compliance_score), "bold")
    _field(console, "Verification coverage", _pct(s.verification_coverage), "bold")
    if s.verified < s.total_requirements:
        console.print(
            Text(
                f"  {s.total_requirements - s.verified} of {s.total_requirements} requirement(s) "
                "were not tested and are not counted as passes.",
                style="dim",
            )
        )
    for notice in report.notices:
        console.print(Text(f"  Note: {notice}", style="yellow"))
    console.print()

    def severity_key(e: AuditEntry) -> int:
        return SEVERITY_ORDER[e.requirement.severity]

    failing = sorted(report.by_status(Status.FAIL), key=severity_key)
    critical = [e for e in failing if e.requirement.severity.value == "critical"]
    other = [e for e in failing if e not in critical]
    groups: list[tuple[str, list[AuditEntry]]] = [
        ("CRITICAL FAILURES", critical),
        ("FAILURES", other),
        ("ERRORS (checker could not run)", report.by_status(Status.ERROR)),
        ("WARNINGS", report.by_status(Status.WARNING)),
        ("UNVERIFIED (not tested)", report.by_status(Status.UNVERIFIED)),
    ]
    for title, entries in groups:
        if not entries:
            continue
        console.print(Text(title, style="bold"))
        console.print(Rule(style="dim"))
        for entry in entries:
            _print_entry(console, entry, build_view(entry))

    passed = report.by_status(Status.PASS)
    if passed:
        console.print(Text("PASSED", style="bold"))
        console.print(Rule(style="dim"))
        for entry in passed:
            if verbose:
                _print_entry(console, entry, build_view(entry))
            else:
                line = Text("  ")
                line.append(entry.requirement.id, style=STATUS_STYLE[Status.PASS])
                line.append(f"  {entry.requirement.description}")
                console.print(line)
        console.print()
