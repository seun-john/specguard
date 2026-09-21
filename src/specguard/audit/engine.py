"""The audit engine: specification + document in, evidence-based report out."""

from __future__ import annotations

import logging
from pathlib import Path

from specguard import __version__
from specguard.audit.scoring import compute_summary
from specguard.audit.semantic import SemanticVerifier
from specguard.audit.validation import check_requirements
from specguard.models.document import Document
from specguard.models.requirement import Requirement, Severity, VerificationType
from specguard.models.result import (
    AuditEntry,
    AuditReport,
    CheckResult,
    DocumentInfo,
    Status,
)
from specguard.models.specification import Specification, SpecificationError
from specguard.rules import AuditContext, ParameterError, RuleRegistry, default_registry
from specguard.utils.text import count_words

log = logging.getLogger(__name__)


class AuditEngine:
    """Runs every enabled requirement of a specification against a document.

    Checkers are looked up in a registry, so new rule types need no engine changes.
    One misbehaving checker produces an ERROR entry; it never aborts the audit.
    """

    def __init__(
        self,
        registry: RuleRegistry | None = None,
        semantic_verifier: SemanticVerifier | None = None,
    ) -> None:
        self.registry = registry or default_registry
        self.semantic_verifier = semantic_verifier

    def audit(
        self,
        specification: Specification,
        document: Document,
        *,
        base_dir: Path | None = None,
    ) -> AuditReport:
        """Audit `document`. Raises SpecificationError if the specification is unusable."""
        issues = check_requirements(specification, base_dir=base_dir, registry=self.registry)
        errors = [i for i in issues if i.level == "error"]
        if errors:
            raise SpecificationError(issues)

        context = AuditContext(base_dir=base_dir)
        entries: list[AuditEntry] = []
        disabled = 0
        for requirement in specification.requirements:
            if not requirement.enabled:
                disabled += 1
                continue
            result = self._run_one(requirement, document, context)
            entries.append(AuditEntry(requirement=requirement, result=result))

        return AuditReport(
            specguard_version=__version__,
            specification_name=specification.name,
            document=self._document_info(document),
            summary=compute_summary(entries, disabled),
            entries=entries,
            notices=self._notices(document, disabled),
        )

    # -- internals ---------------------------------------------------------------------

    def _run_one(
        self, requirement: Requirement, document: Document, context: AuditContext
    ) -> CheckResult:
        vtype = requirement.verification_type
        if vtype is VerificationType.DETERMINISTIC:
            return self._run_checker(requirement, document, context)
        if vtype is VerificationType.SEMANTIC:
            return self._run_semantic(requirement, document)
        if vtype is VerificationType.MANUAL:
            return self._unverified(
                requirement,
                "This requirement needs a human to judge it. SpecGuard cannot test it.",
            )
        return self._unverified(
            requirement,
            f"SpecGuard {__version__} has no checker for this kind of requirement, "
            "so it was not tested.",
        )

    def _run_checker(
        self, requirement: Requirement, document: Document, context: AuditContext
    ) -> CheckResult:
        assert requirement.checker is not None  # guaranteed by validation
        try:
            checker = self.registry.create(requirement.checker, context)
            result = checker.check(document, requirement)
        except ParameterError as exc:
            return self._error(requirement, f"Invalid rule parameters: {exc}")
        except Exception as exc:  # a checker bug must not sink the audit
            log.debug("checker %s failed", requirement.checker, exc_info=True)
            return self._error(
                requirement, f"Checker '{requirement.checker}' failed: {type(exc).__name__}: {exc}"
            )

        result.requirement_id = requirement.id
        result.checker = result.checker or requirement.checker
        if result.status is Status.FAIL and requirement.severity is Severity.INFO:
            # Advisory requirements report violations without failing the audit.
            result.status = Status.WARNING
            result.message += " (advisory: severity is info)"
        return result

    def _run_semantic(self, requirement: Requirement, document: Document) -> CheckResult:
        verifier = self.semantic_verifier
        if verifier is None or not verifier.supports(requirement):
            reason = (
                "No configured verifier supports this requirement."
                if verifier
                else "No semantic verifier is configured."
            )
            return self._unverified(
                requirement,
                f"This requirement needs semantic judgement. {reason} It was not tested.",
            )
        try:
            result = verifier.verify(document, requirement)
        except Exception as exc:
            log.debug("semantic verifier failed", exc_info=True)
            return self._error(
                requirement,
                f"Semantic verifier '{verifier.name}' failed: {type(exc).__name__}: {exc}",
            )
        result.requirement_id = requirement.id
        result.checker = result.checker or verifier.name
        return result

    @staticmethod
    def _unverified(requirement: Requirement, message: str) -> CheckResult:
        evidence = [requirement.notes] if requirement.notes else []
        return CheckResult(
            requirement_id=requirement.id,
            status=Status.UNVERIFIED,
            message=message,
            checker=requirement.checker if requirement.is_deterministic else None,
            evidence=evidence,
            confidence=0.0,
        )

    @staticmethod
    def _error(requirement: Requirement, message: str) -> CheckResult:
        return CheckResult(
            requirement_id=requirement.id,
            status=Status.ERROR,
            message=message,
            checker=requirement.checker,
            confidence=0.0,
        )

    @staticmethod
    def _document_info(document: Document) -> DocumentInfo:
        words = sum(count_words(u.text) for u in document.units())
        return DocumentInfo(
            path=document.path,
            file_type=document.file_type,
            size_bytes=document.size_bytes,
            word_count=words,
            paragraphs=len(document.paragraphs),
            headings=len(document.headings),
            tables=len(document.tables),
            metadata={
                k: v
                for k, v in document.metadata.items()
                if k in ("encoding", "title", "author", "line_count")
            },
        )

    @staticmethod
    def _notices(document: Document, disabled: int) -> list[str]:
        notices: list[str] = []
        if not document.raw_text.strip():
            notices.append("The document contains no text; rules that look for content will fail.")
        if document.metadata.get("encoding") == "cp1252":
            notices.append("The file is not valid UTF-8; it was read as Windows-1252.")
        if disabled:
            notices.append(f"{disabled} disabled requirement(s) were skipped.")
        return notices
