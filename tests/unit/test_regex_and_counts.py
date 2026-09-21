"""forbidden_regex, required_regex, occurrences, element_count and safe regex handling."""

from __future__ import annotations

import pytest
from tests.helpers import md, run_rule, txt

from specguard.models.result import Status
from specguard.rules import default_registry
from specguard.utils.safe_regex import (
    PatternTimeoutError,
    UnsafePatternError,
    compile_pattern,
    finditer_safe,
)


class TestRegexRules:
    def test_forbidden_regex_valid_pattern_matches(self) -> None:
        result = run_rule(txt("Call 555-1234 now"), "forbidden_regex", {"pattern": r"\d{3}-\d{4}"})
        assert result.status is Status.FAIL
        assert result.details["matches"] == 1

    def test_forbidden_regex_no_match_passes(self) -> None:
        assert (
            run_rule(txt("no digits"), "forbidden_regex", {"pattern": r"\d+"}).status is Status.PASS
        )

    def test_required_regex_valid_pattern(self) -> None:
        assert (
            run_rule(txt("Ref: ABC-123"), "required_regex", {"pattern": r"[A-Z]{3}-\d+"}).status
            is Status.PASS
        )
        assert (
            run_rule(txt("nothing"), "required_regex", {"pattern": r"[A-Z]{3}-\d+"}).status
            is Status.FAIL
        )

    def test_flags(self) -> None:
        params = {"pattern": "abc", "flags": ["ignorecase"]}
        assert run_rule(txt("ABC"), "forbidden_regex", params).status is Status.FAIL

    def test_required_regex_all_versus_any(self) -> None:
        params = {"patterns": ["cat", "dog"]}
        assert run_rule(txt("cat"), "required_regex", params).status is Status.FAIL
        assert (
            run_rule(txt("cat"), "required_regex", {**params, "require": "any"}).status
            is Status.PASS
        )

    @pytest.mark.parametrize("checker", ["forbidden_regex", "required_regex"])
    def test_invalid_regex_is_a_validation_problem_not_a_crash(self, checker: str) -> None:
        (problem,) = default_registry.create(checker).validate_parameters({"pattern": "(unclosed"})
        assert "invalid regular expression" in problem

    def test_pattern_matching_the_empty_string_is_refused(self) -> None:
        (problem,) = default_registry.create("forbidden_regex").validate_parameters(
            {"pattern": "a*"}
        )
        assert "empty string" in problem

    def test_overlong_pattern_is_refused(self) -> None:
        problems = default_registry.create("forbidden_regex").validate_parameters(
            {"pattern": "a" * 1001}
        )
        assert problems

    def test_unknown_flag_is_refused(self) -> None:
        assert default_registry.create("forbidden_regex").validate_parameters(
            {"pattern": "a", "flags": ["x"]}
        )


class TestSafeRegex:
    def test_catastrophic_backtracking_is_stopped(self) -> None:
        compiled = compile_pattern(r"(a|aa)+$")
        with pytest.raises(PatternTimeoutError):
            finditer_safe(compiled, "a" * 60 + "b")

    def test_compile_rejects_non_string(self) -> None:
        with pytest.raises(UnsafePatternError):
            compile_pattern("")  # empty


class TestOccurrences:
    doc_text = "climate change matters. Climate change is here. Change is hard."

    def test_at_least_passes_and_reports_locations(self) -> None:
        result = run_rule(
            txt(self.doc_text), "occurrences", {"text": "climate change", "at_least": 2}
        )
        assert result.status is Status.PASS
        assert result.details["occurrences"] == 2

    def test_at_least_fails_with_count(self) -> None:
        result = run_rule(txt(self.doc_text), "occurrences", {"text": "climate change", "min": 3})
        assert result.status is Status.FAIL
        assert "short by 1" in (result.actual or "")

    def test_at_most(self) -> None:
        assert (
            run_rule(txt(self.doc_text), "occurrences", {"text": "change", "at_most": 3}).status
            is Status.PASS
        )
        assert (
            run_rule(txt(self.doc_text), "occurrences", {"text": "change", "at_most": 2}).status
            is Status.FAIL
        )

    def test_exactly(self) -> None:
        assert (
            run_rule(
                txt("a a a"), "occurrences", {"text": "a", "whole_word": True, "exactly": 3}
            ).status
            is Status.PASS
        )
        assert (
            run_rule(txt("a a"), "occurrences", {"text": "a", "exactly": 3}).status is Status.FAIL
        )

    def test_between(self) -> None:
        params = {"text": "a", "whole_word": True, "between": [2, 3]}
        assert run_rule(txt("a"), "occurrences", params).status is Status.FAIL
        assert run_rule(txt("a a"), "occurrences", params).status is Status.PASS
        assert run_rule(txt("a a a a"), "occurrences", params).status is Status.FAIL

    def test_regex_target(self) -> None:
        result = run_rule(txt("v1 v2 v3"), "occurrences", {"pattern": r"v\d", "exactly": 3})
        assert result.status is Status.PASS

    def test_needs_exactly_one_of_text_or_pattern(self) -> None:
        checker = default_registry.create("occurrences")
        assert checker.validate_parameters({"at_least": 1})
        assert checker.validate_parameters({"text": "a", "pattern": "b", "at_least": 1})


class TestElementCount:
    def test_bullets(self) -> None:
        doc = md("- one\n- two\n- three\n")
        assert (
            run_rule(doc, "element_count", {"element": "bullets", "exact": 3}).status is Status.PASS
        )
        assert (
            run_rule(doc, "element_count", {"element": "bullets", "exact": 5}).status is Status.FAIL
        )

    def test_zero_bullets_when_none_allowed(self) -> None:
        assert (
            run_rule(md("- one\n"), "element_count", {"element": "bullets", "exact": 0}).status
            is Status.FAIL
        )

    def test_code_block_present(self) -> None:
        doc = md("Text\n\n```python\nprint(1)\n```\n")
        assert (
            run_rule(doc, "element_count", {"element": "code_blocks", "min": 1}).status
            is Status.PASS
        )
        assert (
            run_rule(md("no code"), "element_count", {"element": "code_blocks", "min": 1}).status
            is Status.FAIL
        )

    def test_references_counted_under_reference_heading(self) -> None:
        doc = md("# Body\n\ntext\n\n# References\n\n- Ref one\n- Ref two\n- Ref three\n")
        result = run_rule(doc, "element_count", {"element": "references", "min": 3})
        assert result.status is Status.PASS
        assert result.confidence < 1.0  # heuristic, and the report says so

    def test_references_without_a_reference_section(self) -> None:
        result = run_rule(
            md("# Body\n\ntext"), "element_count", {"element": "references", "min": 1}
        )
        assert result.status is Status.FAIL
        assert any("No reference-list heading" in e for e in result.evidence)

    def test_headings_by_level(self) -> None:
        doc = md("# A\n\n## B\n\n## C\n")
        assert (
            run_rule(doc, "element_count", {"element": "headings", "level": 2, "exact": 2}).status
            is Status.PASS
        )

    def test_tables(self) -> None:
        doc = md("| a |\n| - |\n| b |\n")
        assert (
            run_rule(doc, "element_count", {"element": "tables", "exact": 1}).status is Status.PASS
        )

    def test_element_is_required(self) -> None:
        assert default_registry.create("element_count").validate_parameters({"min": 1})
