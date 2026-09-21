"""Checker interface and registry.

A checker is a class with a `rule_type` name. Register it and it becomes available as
`checker: <rule_type>` in specifications, with no change to the audit engine:

    from specguard.rules import RuleChecker, register_rule

    @register_rule
    class NoShoutingRule(RuleChecker):
        rule_type = "no_shouting"
        summary = "Fails when a paragraph is all upper case."

        def check(self, document, requirement):
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Location, Status
from specguard.rules.params import ParameterError

# Reports stay readable when a rule matches thousands of times.
MAX_LOCATIONS = 50


@dataclass
class AuditContext:
    """Per-audit settings handed to every checker.

    base_dir: directory that relative file parameters (such as `baseline_file`) are
              resolved against, and may not escape. Usually the specification's folder.
    """

    base_dir: Path | None = None


class RuleChecker(ABC):
    """Tests one kind of requirement against a Document."""

    rule_type: ClassVar[str]
    summary: ClassVar[str] = ""
    parameter_help: ClassVar[dict[str, str]] = {}

    def __init__(self, context: AuditContext | None = None) -> None:
        self.context = context or AuditContext()

    def validate_parameters(self, parameters: Mapping[str, Any]) -> list[str]:
        """Return a list of problems with `parameters`; empty means valid.

        The default implementation runs `parse`, which subclasses use to build their
        typed configuration and raise ParameterError.
        """
        try:
            self.parse(parameters)
        except ParameterError as exc:
            return [str(exc)]
        return []

    def parse(self, parameters: Mapping[str, Any]) -> Any:
        """Turn raw parameters into a typed configuration. Raise ParameterError if invalid."""
        return None

    @abstractmethod
    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        """Test `document` against `requirement` and return the evidence-bearing result."""

    # -- result builders ---------------------------------------------------------------

    def result(
        self,
        requirement: Requirement,
        status: Status,
        message: str,
        *,
        expected: str | None = None,
        actual: str | None = None,
        evidence: list[str] | None = None,
        locations: list[Location] | None = None,
        confidence: float = 1.0,
        remediation_hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> CheckResult:
        """Build a CheckResult, capping locations and recording the checker name."""
        all_locations = locations or []
        details = dict(details or {})
        if len(all_locations) > MAX_LOCATIONS:
            details["locations_total"] = len(all_locations)
            details["locations_truncated"] = True
            all_locations = all_locations[:MAX_LOCATIONS]
        return CheckResult(
            requirement_id=requirement.id,
            status=status,
            message=message,
            expected=expected,
            actual=actual,
            evidence=evidence or [],
            locations=all_locations,
            checker=self.rule_type,
            confidence=confidence,
            remediation_hint=remediation_hint,
            details=details,
        )

    def passed(self, requirement: Requirement, message: str, **kw: Any) -> CheckResult:
        return self.result(requirement, Status.PASS, message, **kw)

    def failed(self, requirement: Requirement, message: str, **kw: Any) -> CheckResult:
        return self.result(requirement, Status.FAIL, message, **kw)

    def unverified(self, requirement: Requirement, message: str, **kw: Any) -> CheckResult:
        return self.result(requirement, Status.UNVERIFIED, message, **kw)


_C = TypeVar("_C", bound=type[RuleChecker])


class RuleRegistry:
    """Maps `rule_type` names to checker classes."""

    def __init__(self) -> None:
        self._checkers: dict[str, type[RuleChecker]] = {}

    def register(self, checker_cls: _C) -> _C:
        """Register a checker class. Usable as a decorator."""
        name = getattr(checker_cls, "rule_type", None)
        if not name or not isinstance(name, str):
            raise TypeError(f"{checker_cls.__name__} must define a string `rule_type`")
        existing = self._checkers.get(name)
        if existing is not None and existing is not checker_cls:
            raise ValueError(f"A checker named '{name}' is already registered")
        self._checkers[name] = checker_cls
        return checker_cls

    def get(self, name: str) -> type[RuleChecker] | None:
        return self._checkers.get(name)

    def names(self) -> list[str]:
        return sorted(self._checkers)

    def create(self, name: str, context: AuditContext | None = None) -> RuleChecker:
        cls = self._checkers[name]
        return cls(context)

    def describe(self) -> list[dict[str, Any]]:
        """Structured descriptions of every registered checker."""
        return [
            {
                "rule_type": name,
                "summary": cls.summary,
                "parameters": dict(cls.parameter_help),
            }
            for name, cls in sorted(self._checkers.items())
        ]


default_registry = RuleRegistry()


def register_rule(checker_cls: _C) -> _C:
    """Register a checker class with the default registry."""
    return default_registry.register(checker_cls)
