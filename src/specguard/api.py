"""The single entry point used by both the CLI and the MCP server.

Nothing here prints or exits. Callers decide how to present results, so the two
front ends cannot drift apart in behaviour.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from specguard.audit.engine import AuditEngine
from specguard.audit.semantic import SemanticVerifier
from specguard.audit.validation import (
    ValidationResult,
    load_specification,
    validate_specification_data,
    validate_specification_file,
)
from specguard.extractors import load_document, load_document_from_text
from specguard.extractors.instructions import ExtractionResult, extract_requirements
from specguard.models.document import Document
from specguard.models.requirement import Category, Requirement, Severity, VerificationType
from specguard.models.result import AuditReport, CheckResult
from specguard.models.specification import Specification, SpecificationError, ValidationIssue
from specguard.rules import AuditContext, RuleRegistry, default_registry

__all__ = [
    "audit_document",
    "audit_file",
    "audit_text",
    "compare_preserved",
    "extract_from_text",
    "list_rules",
    "specification_from_extraction",
    "validate_data",
    "validate_file",
]


def extract_from_text(instructions: str) -> ExtractionResult:
    """Find candidate requirements in prose instructions."""
    return extract_requirements(instructions)


def specification_from_extraction(result: ExtractionResult, name: str) -> Specification:
    """Wrap extracted requirements in a Specification."""
    return Specification(name=name, requirements=result.requirements)


def validate_data(
    data: Any, *, base_dir: Path | None = None, registry: RuleRegistry | None = None
) -> ValidationResult:
    """Validate a specification given as parsed data (a dict)."""
    return validate_specification_data(data, base_dir=base_dir, registry=registry)


def validate_file(path: str | Path, *, registry: RuleRegistry | None = None) -> ValidationResult:
    """Validate a YAML specification file."""
    return validate_specification_file(path, registry=registry)


def audit_document(
    specification: Specification,
    document: Document,
    *,
    base_dir: Path | None = None,
    registry: RuleRegistry | None = None,
    semantic_verifier: SemanticVerifier | None = None,
) -> AuditReport:
    """Audit an already-loaded document."""
    engine = AuditEngine(registry=registry, semantic_verifier=semantic_verifier)
    return engine.audit(specification, document, base_dir=base_dir)


def audit_file(
    document_path: str | Path,
    specification_path: str | Path,
    *,
    registry: RuleRegistry | None = None,
    semantic_verifier: SemanticVerifier | None = None,
) -> AuditReport:
    """Load a specification file and a document, then audit. Never modifies either file.

    Raises FileAccessError (unreadable document or specification) or SpecificationError.
    """
    spec, base_dir = load_specification(specification_path, registry=registry)
    document = load_document(document_path)
    return audit_document(
        spec, document, base_dir=base_dir, registry=registry, semantic_verifier=semantic_verifier
    )


def audit_text(
    content: str,
    specification: Specification | dict[str, Any],
    *,
    file_type: str = "txt",
    base_dir: Path | None = None,
    registry: RuleRegistry | None = None,
    semantic_verifier: SemanticVerifier | None = None,
) -> AuditReport:
    """Audit text held in memory as `txt` or `md`.

    `baseline_file` parameters are refused unless `base_dir` is given.
    """
    if isinstance(specification, dict):
        result = validate_specification_data(specification, base_dir=base_dir, registry=registry)
        if not result.ok or result.spec is None:
            raise SpecificationError(result.issues)
        spec = result.spec
    else:
        spec = specification
    document = load_document_from_text(content, file_type)
    return audit_document(
        spec, document, base_dir=base_dir, registry=registry, semantic_verifier=semantic_verifier
    )


def compare_preserved(
    content: str,
    protected: str | list[str],
    *,
    file_type: str = "txt",
    case_sensitive: bool = True,
    normalize_whitespace: bool = True,
    normalize_quotes: bool = False,
) -> CheckResult:
    """Check that each protected passage appears in `content` exactly, with a diff if not."""
    texts = [protected] if isinstance(protected, str) else list(protected)
    requirement = Requirement(
        id="PRESERVE",
        description="Protected text must be unchanged",
        category=Category.PRESERVATION,
        severity=Severity.CRITICAL,
        verification_type=VerificationType.DETERMINISTIC,
        checker="preserve_text",
        parameters={
            "texts": texts,
            "case_sensitive": case_sensitive,
            "normalize_whitespace": normalize_whitespace,
            "normalize_quotes": normalize_quotes,
        },
    )
    checker = default_registry.create("preserve_text", AuditContext())
    problems = checker.validate_parameters(requirement.parameters)
    if problems:
        raise SpecificationError([ValidationIssue(path="protected", message=p) for p in problems])
    return checker.check(load_document_from_text(content, file_type), requirement)


def list_rules(registry: RuleRegistry | None = None) -> list[dict[str, Any]]:
    """Every registered checker with its summary and parameters."""
    return (registry or default_registry).describe()
