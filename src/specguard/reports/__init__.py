"""Report renderers. Each takes an AuditReport; none re-runs any check."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from specguard.models.result import AuditReport
from specguard.reports.json_report import render_json, report_to_dict
from specguard.reports.markdown_report import render_markdown
from specguard.reports.sarif import render_sarif, report_to_sarif
from specguard.reports.terminal import render_terminal

FORMATS = ("terminal", "json", "markdown", "sarif")


def render_terminal_text(report: AuditReport, *, verbose: bool = False, width: int = 100) -> str:
    """The terminal report as plain text (no colour), for writing to a file."""
    buffer = StringIO()
    console = Console(file=buffer, width=width, force_terminal=False, color_system=None)
    render_terminal(report, console, verbose=verbose)
    return buffer.getvalue()


def render_report(report: AuditReport, fmt: str, *, verbose: bool = False) -> str:
    """Render a report to a string in `fmt` (terminal output is plain text)."""
    if fmt == "json":
        return render_json(report)
    if fmt == "markdown":
        return render_markdown(report)
    if fmt == "sarif":
        return render_sarif(report)
    if fmt == "terminal":
        return render_terminal_text(report, verbose=verbose)
    raise ValueError(f"Unknown format '{fmt}'. Choose from: {', '.join(FORMATS)}")


__all__ = [
    "FORMATS",
    "render_json",
    "render_markdown",
    "render_report",
    "render_sarif",
    "render_terminal",
    "render_terminal_text",
    "report_to_dict",
    "report_to_sarif",
]
