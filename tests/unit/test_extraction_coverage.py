"""Phase 3 additions: order, stated facts, spelling, placeholders, term position, citations."""

from __future__ import annotations

from typing import Any

import pytest
from tests.helpers import md, run_rule, txt

from specguard.extractors.instructions import extract_requirements
from specguard.models.requirement import VerificationType
from specguard.models.result import Status
from specguard.rules import ParameterError, default_registry

DET = VerificationType.DETERMINISTIC


def rule(text: str) -> tuple[str | None, dict[str, Any]]:
    result = extract_requirements(text)
    assert len(result.items) == 1, [r.description for r in result.requirements]
    req = result.items[0].requirement
    assert req.verification_type is DET, (req.verification_type, req.description)
    return req.checker, req.parameters


# -- section order ------------------------------------------------------------------------


class TestSectionOrder:
    doc = md("# Overview\n\ntext\n\n# Methods\n\ntext\n\n# Conclusion\n\ntext\n")

    def test_in_order_passes(self) -> None:
        result = run_rule(
            self.doc, "required_section", {"headings": ["Overview", "Conclusion"], "ordered": True}
        )
        assert result.status is Status.PASS

    def test_swapped_fails_and_says_so(self) -> None:
        result = run_rule(
            self.doc, "required_section", {"headings": ["Conclusion", "Overview"], "ordered": True}
        )
        assert result.status is Status.FAIL
        assert result.details["order_found"] == ["Overview", "Conclusion"]

    def test_missing_heading_still_fails_as_missing(self) -> None:
        result = run_rule(
            self.doc, "required_section", {"headings": ["Overview", "Risks"], "ordered": True}
        )
        assert result.status is Status.FAIL
        assert result.details["missing"] == ["Risks"]

    def test_ordered_needs_require_all(self) -> None:
        checker = default_registry.create("required_section")
        with pytest.raises(ParameterError):
            checker.parse({"headings": ["A", "B"], "ordered": True, "require": "any"})

    @pytest.mark.parametrize(
        ("text", "headings"),
        [
            ("Put the Proposal section before the Risks section.", ["Proposal", "Risks"]),
            (
                "The Methodology section must come before the Recommendations section.",
                ["Methodology", "Recommendations"],
            ),
            (
                "The Getting There section must come before the Where to Stay section.",
                ["Getting There", "Where to Stay"],
            ),
            ("Place the Risks section after the Proposal section.", ["Proposal", "Risks"]),
        ],
    )
    def test_extraction(self, text: str, headings: list[str]) -> None:
        assert rule(text) == ("required_section", {"headings": headings, "ordered": True})

    def test_lowercase_nouns_are_not_section_names(self) -> None:
        result = extract_requirements("Put the summary section before the details section.")
        assert all(i.requirement.checker != "required_section" for i in result.items)


# -- stated facts -------------------------------------------------------------------------


class TestStatedFacts:
    @pytest.mark.parametrize(
        ("text", "value"),
        [
            ("State the total cost as 19,700 pounds.", "19,700 pounds"),
            ("Say that 150 people have signed up.", "150 people"),
            ("Say that the event takes place on 5 May.", "5 May"),
        ],
    )
    def test_extraction(self, text: str, value: str) -> None:
        assert rule(text) == ("required_text", {"values": [value], "whole_word": True})

    def test_a_longer_number_is_not_the_stated_one(self) -> None:
        req_params = {"values": ["5 May"], "whole_word": True}
        assert (
            run_rule(md("The event is on 15 May."), "required_text", req_params).status
            is Status.FAIL
        )
        assert (
            run_rule(md("The event is on 5 May."), "required_text", req_params).status
            is Status.PASS
        )

    def test_a_statement_without_a_figure_is_not_a_fact_rule(self) -> None:
        result = extract_requirements("State the main argument as clearly as you can.")
        assert all(i.requirement.checker != "required_text" for i in result.items)


# -- spelling -----------------------------------------------------------------------------


class TestSpellingVariant:
    def test_american_words_fail_a_british_document(self) -> None:
        result = run_rule(
            md("The color of the center was bright.\n"), "spelling_variant", {"variant": "british"}
        )
        assert result.status is Status.FAIL
        assert set(result.details["other_variant_words"]) == {"color", "center"}

    def test_british_document_passes_with_lower_confidence(self) -> None:
        result = run_rule(
            md("The colour of the centre was bright.\n"), "spelling_variant", {"variant": "british"}
        )
        assert result.status is Status.PASS
        assert result.confidence < 1.0
        assert any("word list" in e or "spelling pairs" in e for e in result.evidence)

    def test_british_words_fail_an_american_document(self) -> None:
        result = run_rule(
            md("We will organise the colour scheme.\n"), "spelling_variant", {"variant": "american"}
        )
        assert result.status is Status.FAIL
        assert set(result.details["other_variant_words"]) == {"organise", "colour"}

    def test_oxford_ize_is_accepted_in_a_british_document(self) -> None:
        result = run_rule(
            md("We will organize and recognize the team.\n"),
            "spelling_variant",
            {"variant": "british"},
        )
        assert result.status is Status.PASS

    def test_inflections_are_found(self) -> None:
        text = "The labeled boxes were traveling to the theater.\n"
        result = run_rule(md(text), "spelling_variant", {"variant": "british"})
        assert set(result.details["other_variant_words"]) == {"labeled", "traveling", "theater"}

    def test_words_that_only_contain_a_stem_are_not_flagged(self) -> None:
        text = "The laboratory colonel mold-free centered Honorary award.\n"
        result = run_rule(md(text), "spelling_variant", {"variant": "british"})
        assert "laboratory" not in result.details["other_variant_words"]
        assert "colonel" not in result.details["other_variant_words"]

    def test_quotation_marks_are_reported_not_hidden(self) -> None:
        text = 'A talk was titled "Color and Light in Parks". The colour was good.\n'
        result = run_rule(md(text), "spelling_variant", {"variant": "british"})
        assert result.status is Status.PASS
        assert result.details["ignored_in_quotes"] == {"color": 1}
        assert any("quotation marks" in e for e in result.evidence)

    def test_allow_list(self) -> None:
        text = "The Color Purple was read.\n"
        failing = run_rule(md(text), "spelling_variant", {"variant": "british"})
        passing = run_rule(md(text), "spelling_variant", {"variant": "british", "allow": ["Color"]})
        assert failing.status is Status.FAIL
        assert passing.status is Status.PASS

    def test_variant_is_required(self) -> None:
        checker = default_registry.create("spelling_variant")
        with pytest.raises(ParameterError):
            checker.parse({})

    @pytest.mark.parametrize(
        ("text", "variant"),
        [
            ("Write in British English.", "british"),
            ("Use British spelling throughout.", "british"),
            ("Write in US English.", "american"),
            ("Use American spelling.", "american"),
            ("The document must use UK English.", "british"),
        ],
    )
    def test_extraction(self, text: str, variant: str) -> None:
        assert rule(text) == ("spelling_variant", {"variant": variant})

    def test_mentioning_a_variant_without_an_instruction_is_not_a_rule(self) -> None:
        result = extract_requirements("Our readers are mostly American English speakers.")
        assert all(i.requirement.checker != "spelling_variant" for i in result.items)


# -- placeholders -------------------------------------------------------------------------

_PLACEHOLDER_TEXT = (
    "Leave no placeholder text such as [TBC] or [insert name] in the finished piece."
)


class TestPlaceholders:
    def _params(self) -> dict[str, Any]:
        checker, params = rule(_PLACEHOLDER_TEXT)
        assert checker == "forbidden_regex"
        return params

    @pytest.mark.parametrize(
        "bad", ["Contact [insert name] today.", "Cost: [TBC].", "Date TBD.", "Lorem ipsum dolor."]
    )
    def test_placeholders_are_found(self, bad: str) -> None:
        assert run_rule(md(bad + "\n"), "forbidden_regex", self._params()).status is Status.FAIL

    @pytest.mark.parametrize(
        "good",
        [
            "The date is to be confirmed in plain prose.",
            "See reference [1] and the note [2, 3].",
            "She said [sic] once.",
        ],
    )
    def test_ordinary_text_is_not_a_placeholder(self, good: str) -> None:
        assert run_rule(md(good + "\n"), "forbidden_regex", self._params()).status is Status.PASS

    def test_word_placeholder_in_a_different_sense_is_not_extracted(self) -> None:
        result = extract_requirements("Explain how a placeholder works in a template engine.")
        assert all(i.requirement.checker != "forbidden_regex" for i in result.items)


# -- closing section ----------------------------------------------------------------------


class TestClosingConclusion:
    def test_extraction_requires_the_heading_only(self) -> None:
        result = extract_requirements("Finish with a short conclusion.")
        req = result.items[0].requirement
        assert (req.checker, req.parameters) == (
            "required_section",
            {"headings": [["Conclusion", "Conclusions"]]},
        )
        assert "not that it comes last" in (req.notes or "")


# -- position of a term -------------------------------------------------------------------


class TestTermPosition:
    doc = md(
        "# Report\n\n## Introduction\n\nThis opens with Project Kestrel.\n\n- Item with Zebra\n\nMiddle text.\n\nEnd with Zebra.\n"
    )

    def test_first_paragraph(self) -> None:
        params = {"values": ["Project Kestrel"], "within": "first_paragraph"}
        assert run_rule(self.doc, "required_text", params).status is Status.PASS

    def test_term_only_at_the_end_fails_for_first_paragraph(self) -> None:
        params = {"values": ["Zebra"], "within": "first_paragraph"}
        assert run_rule(self.doc, "required_text", params).status is Status.FAIL

    def test_last_paragraph(self) -> None:
        params = {"values": ["Zebra"], "within": "last_paragraph"}
        assert run_rule(self.doc, "required_text", params).status is Status.PASS

    def test_list_items_and_headings_do_not_count_as_paragraphs(self) -> None:
        text = "# Introduction\n\n- Zebra first\n\nPlain opening.\n"
        params = {"values": ["Zebra"], "within": "first_paragraph"}
        assert run_rule(md(text), "required_text", params).status is Status.FAIL

    def test_no_paragraph_is_unverified(self) -> None:
        params = {"values": ["x"], "within": "first_paragraph"}
        assert (
            run_rule(md("# Only a heading\n"), "required_text", params).status is Status.UNVERIFIED
        )

    def test_bad_value_is_rejected(self) -> None:
        checker = default_registry.create("required_text")
        with pytest.raises(ParameterError):
            checker.parse({"values": ["x"], "within": "middle"})

    @pytest.mark.parametrize(
        ("text", "term", "where"),
        [
            (
                "Mention the Kitchen Garden Trust in the opening paragraph.",
                "Kitchen Garden Trust",
                "first_paragraph",
            ),
            (
                "Mention the Seaglass Blue in the final paragraph.",
                "Seaglass Blue",
                "last_paragraph",
            ),
        ],
    )
    def test_extraction(self, text: str, term: str, where: str) -> None:
        assert rule(text) == ("required_text", {"values": [term], "within": where})


# -- citation style -----------------------------------------------------------------------


class TestCitationStyle:
    def _params(self, text: str) -> dict[str, Any]:
        checker, params = rule(text)
        assert checker == "required_regex"
        return params

    def test_numbered(self) -> None:
        params = self._params("Use numbered citations in square brackets, such as [1].")
        assert (
            run_rule(
                md("As shown before [1], and later [2, 3].\n"), "required_regex", params
            ).status
            is Status.PASS
        )
        assert (
            run_rule(md("As shown by (Smith, 2020).\n"), "required_regex", params).status
            is Status.FAIL
        )

    def test_author_year(self) -> None:
        params = self._params("Use author and year citations in brackets, such as (Smith, 2020).")
        for good in (
            "As shown (Smith, 2020).",
            "As shown (Smith and Jones, 2019a).",
            "(Lee et al., 2021, p. 4)",
        ):
            assert run_rule(md(good + "\n"), "required_regex", params).status is Status.PASS, good
        assert (
            run_rule(md("As shown before [1].\n"), "required_regex", params).status is Status.FAIL
        )

    def test_a_citation_count_is_still_handled_by_the_count_matcher(self) -> None:
        result = extract_requirements("Include at least 5 citations.")
        assert result.items[0].requirement.checker != "required_regex"


# -- bulleted list count ------------------------------------------------------------------


class TestBulletedListCount:
    @pytest.mark.parametrize(
        ("text", "params"),
        [
            (
                "Include a bulleted list of exactly 5 action points.",
                {"element": "bullets", "exact": 5},
            ),
            ("Include a bulleted list of at least 3 items.", {"element": "bullets", "min": 3}),
            (
                "Add a numbered list of no more than four steps.",
                {"element": "numbered_items", "max": 4},
            ),
        ],
    )
    def test_extraction(self, text: str, params: dict[str, Any]) -> None:
        assert rule(text) == ("element_count", params)

    def test_unqualified_quantity_stays_manual(self) -> None:
        result = extract_requirements("Include a bulleted list of 5 action points.")
        assert result.items[0].requirement.verification_type is not DET

    def test_exactly_before_a_number_is_not_preservation(self) -> None:
        result = extract_requirements("Include a bulleted list of exactly 5 action points.")
        assert result.items[0].requirement.checker == "element_count"

    def test_exactly_as_written_is_still_preservation(self) -> None:
        result = extract_requirements("Keep the approved wording exactly as written.")
        assert result.items[0].requirement.description.startswith("Preserve")


# -- what remains undecided ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Keep the tone formal and professional.",
        "Write for a general reader with no specialist knowledge, so avoid jargon.",
    ],
)
def test_tone_and_audience_stay_unverified(text: str) -> None:
    result = extract_requirements(text)
    assert result.items[0].requirement.verification_type is VerificationType.SEMANTIC


def test_plain_text_headings_are_ordered_too() -> None:
    doc = txt("Introduction\n\nSome text here.\n\nConclusion\n\nMore text here.\n")
    params = {"headings": ["Introduction", "Conclusion"], "ordered": True}
    assert run_rule(doc, "required_section", params).status is Status.PASS
