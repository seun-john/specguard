from __future__ import annotations

import pytest
from tests.helpers import md, run_rule, txt

from specguard.models.result import Status
from specguard.rules.params import ParameterError
from specguard.utils.text import count_words

TEN_WORDS = "one two three four five six seven eight nine ten"


class TestCountWords:
    def test_hyphenated_and_apostrophe_words_count_once(self) -> None:
        assert count_words("well-known don't stop") == 3

    def test_numbers_with_separators_count_once(self) -> None:
        assert count_words("Revenue was 1,500 or 3.14 units") == 6

    def test_punctuation_and_markdown_markers_are_not_words(self) -> None:
        assert count_words("# Title — **bold** - item") == 3

    def test_whitespace_method_matches_word_style_counting(self) -> None:
        assert count_words("a — b", "whitespace") == 3
        assert count_words("a — b") == 2

    def test_empty_text(self) -> None:
        assert count_words("") == 0


class TestWordCountRule:
    def test_under_minimum_fails_with_actual_count(self) -> None:
        result = run_rule(txt(TEN_WORDS), "word_count", {"min": 11})
        assert result.status is Status.FAIL
        assert result.details["word_count"] == 10
        assert "short by 1" in (result.actual or "")

    def test_exactly_minimum_passes(self) -> None:
        assert run_rule(txt(TEN_WORDS), "word_count", {"min": 10}).status is Status.PASS

    def test_exactly_maximum_passes(self) -> None:
        assert run_rule(txt(TEN_WORDS), "word_count", {"max": 10}).status is Status.PASS

    def test_over_maximum_fails(self) -> None:
        result = run_rule(txt(TEN_WORDS), "word_count", {"max": 9})
        assert result.status is Status.FAIL
        assert "over by 1" in (result.actual or "")

    def test_empty_content_fails_a_minimum(self) -> None:
        result = run_rule(txt(""), "word_count", {"min": 1})
        assert result.status is Status.FAIL
        assert result.details["word_count"] == 0

    def test_empty_content_satisfies_a_maximum(self) -> None:
        assert run_rule(txt(""), "word_count", {"max": 5}).status is Status.PASS

    @pytest.mark.parametrize(
        ("count", "expected"), [(9, Status.FAIL), (10, Status.PASS), (11, Status.FAIL)]
    )
    def test_exact(self, count: int, expected: Status) -> None:
        text = " ".join(["word"] * count)
        assert run_rule(txt(text), "word_count", {"exact": 10}).status is expected

    def test_between_is_inclusive(self) -> None:
        assert run_rule(txt(TEN_WORDS), "word_count", {"between": [10, 12]}).status is Status.PASS
        assert run_rule(txt(TEN_WORDS), "word_count", {"between": [11, 12]}).status is Status.FAIL

    def test_aliases_are_accepted(self) -> None:
        assert (
            run_rule(txt(TEN_WORDS), "word_count", {"at_least": 5, "at_most": 10}).status
            is Status.PASS
        )

    def test_exclude_sections_removes_whole_section(self) -> None:
        doc = md("# Body\n\none two three\n\n# References\n\nfour five six seven eight\n")
        full = run_rule(doc, "word_count", {"max": 100})
        trimmed = run_rule(doc, "word_count", {"max": 100, "exclude_sections": ["References"]})
        assert full.details["word_count"] == 3 + 1 + 5 + 1
        assert trimmed.details["word_count"] == 1 + 3

    def test_missing_excluded_section_is_reported_not_silently_ignored(self) -> None:
        result = run_rule(
            md("# A\n\ntext"), "word_count", {"max": 10, "exclude_sections": ["Appendix"]}
        )
        assert any("Appendix" in line or "appendix" in line for line in result.evidence)

    def test_headings_can_be_left_out(self) -> None:
        doc = md("# Two Words\n\nthree words here")
        assert (
            run_rule(doc, "word_count", {"max": 10, "include_headings": False}).details[
                "word_count"
            ]
            == 3
        )

    def test_table_text_counts_by_default(self) -> None:
        doc = md("| a | b |\n| - | - |\n| c | d |\n")
        assert run_rule(doc, "word_count", {"max": 10}).details["word_count"] == 4

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"exact": 5, "min": 1},
            {"min": 9, "max": 3},
            {"max": "many"},
            {"maxx": 3},
            {"max": -1},
        ],
    )
    def test_invalid_parameters_are_rejected(self, params: dict[str, object]) -> None:
        from specguard.rules import default_registry

        problems = default_registry.create("word_count").validate_parameters(params)
        assert problems

    def test_typo_in_parameter_name_suggests_the_right_one(self) -> None:
        from specguard.rules import default_registry

        (message,) = default_registry.create("word_count").validate_parameters({"maxx": 3})
        assert "max" in message and "Did you mean" in message

    def test_parse_error_is_a_parameter_error(self) -> None:
        from specguard.rules.word_count import WordCountRule

        with pytest.raises(ParameterError):
            WordCountRule().parse({})
