"""Checkers. Importing this package registers every built-in rule."""

from specguard.rules import (  # noqa: F401  (imported for registration)
    file_rules,
    forbidden_text,
    occurrences,
    preservation,
    punctuation,
    regex,
    required_text,
    sections,
    word_count,
)
from specguard.rules.base import (
    AuditContext,
    RuleChecker,
    RuleRegistry,
    default_registry,
    register_rule,
)
from specguard.rules.params import ParameterError

__all__ = [
    "AuditContext",
    "ParameterError",
    "RuleChecker",
    "RuleRegistry",
    "default_registry",
    "register_rule",
]
