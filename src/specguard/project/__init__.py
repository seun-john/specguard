"""Project-level audits: does a repository back up a "done" claim, and are its instruction
files consistent? These work on a folder, not on one document."""

from specguard.project.context import audit_context
from specguard.project.done import audit_done, capture_command, snapshot
from specguard.project.report import ProjectReport, render_project_report
from specguard.project.scope import audit_scope, load_baseline, manifest

__all__ = [
    "ProjectReport",
    "audit_context",
    "audit_done",
    "audit_scope",
    "capture_command",
    "load_baseline",
    "manifest",
    "render_project_report",
    "snapshot",
]
