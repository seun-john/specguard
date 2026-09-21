"""Optional semantic verification: the seam for future LLM or human-in-the-loop checks.

SpecGuard never calls an external service by itself. An application that wants semantic
checks (for example "Use British English" or "Maintain a professional tone") passes an
object implementing this interface to `AuditEngine`. Without one, semantic requirements
are reported UNVERIFIED.

An implementation is responsible for its own privacy and cost decisions; the document
text it receives is exactly what it may choose to send anywhere.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult


class SemanticVerifier(ABC):
    """Evaluates requirements that need language understanding."""

    name: str = "semantic-verifier"

    @abstractmethod
    def supports(self, requirement: Requirement) -> bool:
        """True if this verifier can judge `requirement`."""

    @abstractmethod
    def verify(self, document: Document, requirement: Requirement) -> CheckResult:
        """Judge the requirement. Return PASS/FAIL/WARNING with evidence and a `confidence`,
        or UNVERIFIED when unsure. Never return PASS without evidence."""
