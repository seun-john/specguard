"""forbidden_text, required_text, forbidden_punctuation."""

from __future__ import annotations

from tests.helpers import md, run_rule, txt

from specguard.models.result import Status


class TestForbiddenText:
    def test_present_text_fails_with_location_and_count(self) -> None:
        doc = txt("First paragraph.\n\nThis has a delve in it.\n")
        result = run_rule(doc, "forbidden_text", {"values": ["delve"]})
        assert result.status is Status.FAIL
        assert result.details["occurrences"] == 1
        assert result.locations[0].paragraph == 2
        assert result.locations[0].line == 3
        assert "delve" in (result.locations[0].excerpt or "")

    def test_absent_text_passes(self) -> None:
        assert (
            run_rule(txt("clean text"), "forbidden_text", {"values": ["delve"]}).status
            is Status.PASS
        )

    def test_case_insensitive_by_default(self) -> None:
        assert (
            run_rule(txt("DELVE in"), "forbidden_text", {"values": ["delve"]}).status is Status.FAIL
        )

    def test_case_sensitive_option(self) -> None:
        params = {"values": ["delve"], "case_sensitive": True}
        assert run_rule(txt("DELVE in"), "forbidden_text", params).status is Status.PASS
        assert run_rule(txt("delve in"), "forbidden_text", params).status is Status.FAIL

    def test_multiple_occurrences_are_all_reported(self) -> None:
        doc = txt("delve one.\n\nnothing.\n\ndelve two, delve three.")
        result = run_rule(doc, "forbidden_text", {"value": "delve"})
        assert result.details["occurrences"] == 3
        assert len(result.locations) == 3
        assert {loc.paragraph for loc in result.locations} == {1, 3}

    def test_list_of_values_counts_each(self) -> None:
        result = run_rule(txt("alpha beta alpha"), "forbidden_text", {"values": ["alpha", "beta"]})
        assert result.details["by_value"] == {"alpha": 2, "beta": 1}

    def test_whole_word_ignores_substrings(self) -> None:
        params = {"values": ["art"], "whole_word": True}
        assert (
            run_rule(txt("an article about parties"), "forbidden_text", params).status
            is Status.PASS
        )
        assert run_rule(txt("the art of it"), "forbidden_text", params).status is Status.FAIL

    def test_substring_matches_without_whole_word(self) -> None:
        assert (
            run_rule(txt("an article"), "forbidden_text", {"values": ["art"]}).status is Status.FAIL
        )

    def test_phrase_matches_across_a_line_wrap(self) -> None:
        result = run_rule(
            txt("we must not use the\nphrase here"), "forbidden_text", {"values": ["the phrase"]}
        )
        assert result.status is Status.FAIL
        assert result.locations[0].line == 1

    def test_markdown_emphasis_does_not_hide_a_phrase(self) -> None:
        result = run_rule(
            md("This is **very important** work"), "forbidden_text", {"values": ["very important"]}
        )
        assert result.status is Status.FAIL

    def test_line_number_inside_a_multiline_paragraph(self) -> None:
        result = run_rule(
            txt("line one\nline two\nline three has delve"), "forbidden_text", {"values": ["delve"]}
        )
        assert result.locations[0].line == 3

    def test_code_blocks_can_be_excluded(self) -> None:
        doc = md("Prose.\n\n```\nTODO in code\n```\n")
        assert run_rule(doc, "forbidden_text", {"values": ["TODO"]}).status is Status.FAIL
        excluded = run_rule(
            doc, "forbidden_text", {"values": ["TODO"], "exclude_code_blocks": True}
        )
        assert excluded.status is Status.PASS

    def test_table_cell_location(self) -> None:
        doc = md("| a | b |\n| - | - |\n| ok | delve |\n")
        (loc,) = run_rule(doc, "forbidden_text", {"values": ["delve"]}).locations
        assert (loc.table, loc.row, loc.column) == (1, 2, 2)
        assert loc.describe().startswith("line 3, table 1, row 2, column 2")


class TestRequiredText:
    def test_all_present_passes(self) -> None:
        result = run_rule(txt("alpha and beta"), "required_text", {"values": ["alpha", "beta"]})
        assert result.status is Status.PASS

    def test_one_missing_fails_and_names_it(self) -> None:
        result = run_rule(txt("alpha only"), "required_text", {"values": ["alpha", "beta"]})
        assert result.status is Status.FAIL
        assert result.details["missing"] == ["beta"]
        assert "beta" in result.message

    def test_require_any_passes_with_one(self) -> None:
        params = {"values": ["alpha", "beta"], "require": "any"}
        assert run_rule(txt("alpha only"), "required_text", params).status is Status.PASS

    def test_require_any_fails_with_none(self) -> None:
        params = {"values": ["gamma", "beta"], "require": "any"}
        assert run_rule(txt("alpha only"), "required_text", params).status is Status.FAIL

    def test_case_sensitivity(self) -> None:
        assert run_rule(txt("Alpha"), "required_text", {"value": "alpha"}).status is Status.PASS
        params = {"value": "alpha", "case_sensitive": True}
        assert run_rule(txt("Alpha"), "required_text", params).status is Status.FAIL


class TestForbiddenPunctuation:
    def test_em_dash_by_name(self) -> None:
        result = run_rule(txt("one — two"), "forbidden_punctuation", {"marks": ["em_dash"]})
        assert result.status is Status.FAIL
        assert result.details["occurrences"] == 1

    def test_names_are_forgiving(self) -> None:
        for name in ("em dash", "em-dash", "em dashes", "EM_DASH"):
            result = run_rule(txt("a — b"), "forbidden_punctuation", {"marks": [name]})
            assert result.status is Status.FAIL, name

    def test_literal_character(self) -> None:
        assert (
            run_rule(txt("a; b"), "forbidden_punctuation", {"marks": [";"]}).status is Status.FAIL
        )

    def test_hyphen_is_not_an_em_dash(self) -> None:
        assert (
            run_rule(txt("well-known"), "forbidden_punctuation", {"marks": ["em_dash"]}).status
            is Status.PASS
        )

    def test_nothing_is_forbidden_unless_configured(self) -> None:
        from specguard.rules import default_registry

        assert default_registry.create("forbidden_punctuation").validate_parameters({})

    def test_max_allowed_tolerates_a_few(self) -> None:
        params = {"marks": ["exclamation_mark"], "max_allowed": 2}
        assert run_rule(txt("Yes! No!"), "forbidden_punctuation", params).status is Status.PASS
        assert run_rule(txt("Yes! No! Wow!"), "forbidden_punctuation", params).status is Status.FAIL

    def test_unknown_name_is_rejected(self) -> None:
        from specguard.rules import default_registry

        (problem,) = default_registry.create("forbidden_punctuation").validate_parameters(
            {"marks": ["squiggle"]}
        )
        assert "squiggle" in problem
