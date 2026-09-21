"""Data models shared by every layer."""

from specguard.models.document import Document, Heading, Paragraph, Table, TextUnit
from specguard.models.requirement import (
    SEVERITY_ORDER,
    SEVERITY_WEIGHTS,
    Category,
    Requirement,
    Severity,
    VerificationType,
)
from specguard.models.result import (
    AuditEntry,
    AuditReport,
    CheckResult,
    DocumentInfo,
    Location,
    Status,
    Summary,
)
from specguard.models.specification import (
    Specification,
    SpecificationError,
    ValidationIssue,
)

__all__ = [
    "SEVERITY_ORDER",
    "SEVERITY_WEIGHTS",
    "AuditEntry",
    "AuditReport",
    "Category",
    "CheckResult",
    "Document",
    "DocumentInfo",
    "Heading",
    "Location",
    "Paragraph",
    "Requirement",
    "Severity",
    "Specification",
    "SpecificationError",
    "Status",
    "Summary",
    "Table",
    "TextUnit",
    "ValidationIssue",
    "VerificationType",
]
