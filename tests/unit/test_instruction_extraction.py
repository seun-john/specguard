"""Natural-language extraction: deterministic where unambiguous, never invented otherwise."""

from __future__ import annotations

from typing import Any

import pytest
from tests.helpers import FIXTURES

from specguard.extractors.instructions import ExtractionResult, extract_requirements
from specguard.models.requirement import Category, Requirement, VerificationType

DET = VerificationType.DETERMINISTIC


def one(text: str) -> Requirement:
    result = extract_requirements(text)
    assert len(result.items) == 1, [r.description for r in result.requirements]
    return result.items[0].requirement


def rule(text: str) -> tuple[str | None, dict[str, Any]]:
    req = one(text)
    assert req.verification_type is DET, (req.verification_type, req.description)
    return req.checker, req.parameters


class TestWordLimits:
    @pytest.mark.parametrize(
        ("text", "params"),
        [
            ("at least 2000 words", {"min": 2000}),
            ("The report needs a minimum of 2,000 words.", {"min": 2000}),
            ("Minimum 2000 words.", {"min": 2000}),
            ("Write no fewer than 500 words.", {"min": 500}),
            ("Write more than 500 words.", {"min": 501}),
            ("No more than 3000 words.", {"max": 3000}),
            ("Maximum 3000 words.", {"max": 3000}),
            ("The document must not exceed 3000 words.", {"max": 3000}),
            ("Keep the report below 3,000 words.", {"max": 2999}),
            ("Stay under 3000 words.", {"max": 2999}),
            ("Write exactly 1500 words.", {"exact": 1500}),
            ("Do not write more than 3000 words.", {"max": 3000}),
            ("Do not go under 500 words.", {"min": 500}),
        ],
    )
    def test_single_limit(self, text: str, params: dict[str, int]) -> None:
        assert rule(text) == ("word_count", params)

    def test_between_gives_a_minimum_and_a_maximum(self) -> None:
        result = extract_requirements("Write between 2,000 and 3,000 words.")
        assert [(r.checker, r.parameters) for r in result.requirements] == [
            ("word_count", {"min": 2000}),
            ("word_count", {"max": 3000}),
        ]

    def test_range_with_a_dash(self) -> None:
        result = extract_requirements("Aim for 1500-2000 words.")
        assert [r.parameters for r in result.requirements] == [{"min": 1500}, {"max": 2000}]

    def test_negated_bound_is_not_read_as_its_opposite(self) -> None:
        # "no more than" must not also produce "more than" (a bug an earlier draft had).
        result = extract_requirements("Write no more than 3000 words.")
        assert [r.parameters for r in result.requirements] == [{"max": 3000}]

    def test_approximate_length_is_not_turned_into_a_limit(self) -> None:
        req = one("Write a 1500-word essay.")
        assert req.verification_type is VerificationType.MANUAL
        assert req.checker is None
        assert "approximate" in (req.notes or "")

    def test_page_limits_are_unsupported_not_guessed(self) -> None:
        req = one("The report must not exceed 10 pages.")
        assert req.verification_type is VerificationType.UNSUPPORTED
        assert req.checker is None


class TestForbidden:
    def test_em_dashes(self) -> None:
        assert rule("Do not use em dashes.") == ("forbidden_punctuation", {"marks": ["em_dash"]})

    def test_several_marks_in_one_requirement(self) -> None:
        assert rule("Do not use em dashes or semicolons.") == (
            "forbidden_punctuation",
            {"marks": ["em_dash", "semicolon"]},
        )

    def test_excessive_exclamation_marks_gets_no_invented_threshold(self) -> None:
        req = one("Avoid excessive exclamation marks.")
        assert req.verification_type is VerificationType.MANUAL
        assert "max_allowed" in (req.notes or "")

    def test_quoted_phrase(self) -> None:
        assert rule('Do not use the phrase "in conclusion".') == (
            "forbidden_text",
            {"values": ["in conclusion"]},
        )

    def test_quoted_word_is_whole_word(self) -> None:
        assert rule('Avoid the word "very".') == (
            "forbidden_text",
            {"values": ["very"], "whole_word": True},
        )

    def test_never_include_quoted(self) -> None:
        assert rule('Never include "lorem ipsum".')[1] == {"values": ["lorem ipsum"]}

    def test_unquoted_word_list(self) -> None:
        assert rule("Avoid the words delve, tapestry and leverage.")[1] == {
            "values": ["delve", "tapestry", "leverage"],
            "whole_word": True,
        }

    def test_placeholder_tokens_are_case_sensitive(self) -> None:
        assert rule("No TODO or TBD anywhere.")[1] == {
            "values": ["TODO", "TBD"],
            "whole_word": True,
            "case_sensitive": True,
        }

    def test_forbidden_element(self) -> None:
        assert rule("Do not use bullet points.") == (
            "element_count",
            {"element": "bullets", "exact": 0},
        )


class TestRequired:
    def test_named_section(self) -> None:
        assert rule("Include a conclusion.") == (
            "required_section",
            {"headings": [["Conclusion", "Conclusions"]]},
        )

    def test_references_accept_common_alternatives(self) -> None:
        checker, params = rule("The report must include references.")
        assert checker == "required_section"
        assert "Bibliography" in params["headings"][0]

    def test_section_list_gives_one_requirement_per_heading(self) -> None:
        result = extract_requirements(
            "Include the sections Background, Findings, Recommendations and Conclusion."
        )
        names = [r.parameters["headings"][0] for r in result.requirements]
        assert names == ["Background", "Findings", "Recommendations", ["Conclusion", "Conclusions"]]
        assert {r.checker for r in result.requirements} == {"required_section"}

    def test_bulleted_section_list(self) -> None:
        result = extract_requirements(
            "Include the following sections:\n- Introduction\n- Discussion\n"
        )
        assert [r.parameters["headings"][0] for r in result.requirements] == [
            "Introduction",
            "Discussion",
        ]

    def test_several_named_sections_in_one_sentence(self) -> None:
        result = extract_requirements("Include an introduction, methodology and conclusion.")
        assert len(result.requirements) == 3

    def test_quoted_heading(self) -> None:
        assert rule('Use the heading "Methodology".') == (
            "required_section",
            {"headings": ["Methodology"]},
        )

    def test_required_phrase(self) -> None:
        assert rule('Include the phrase "stakeholder engagement".') == (
            "required_text",
            {"values": ["stakeholder engagement"]},
        )

    def test_required_terminology_list(self) -> None:
        assert rule('Use the terminology "health equity" and "social determinants".')[1] == {
            "values": ["health equity", "social determinants"]
        }

    @pytest.mark.parametrize(
        "text",
        ["Include a summary of the findings.", "Include a section on risk management."],
    )
    def test_content_requests_are_not_mistaken_for_headings(self, text: str) -> None:
        assert one(text).verification_type is VerificationType.SEMANTIC

    def test_file_type(self) -> None:
        assert rule("Deliver the result as a Word document.") == (
            "file_type",
            {"extensions": ["docx"]},
        )
        assert rule("The output must be Markdown.") == ("file_type", {"extensions": ["md"]})


class TestCounts:
    def test_references_at_least(self) -> None:
        assert rule("Include at least 30 references.") == (
            "element_count",
            {"element": "references", "min": 30},
        )

    def test_sources_count_as_references(self) -> None:
        assert rule("Cite at least 10 sources.")[1] == {"element": "references", "min": 10}

    def test_bullets_exactly(self) -> None:
        assert rule("Use exactly 5 bullet points.") == (
            "element_count",
            {"element": "bullets", "exact": 5},
        )

    def test_number_words(self) -> None:
        assert rule("Include at least five tables.")[1] == {"element": "tables", "min": 5}

    def test_negated_maximum(self) -> None:
        assert rule("Do not use more than 5 bullet points.")[1] == {"element": "bullets", "max": 5}

    def test_bare_quantity_is_ambiguous_so_not_tested(self) -> None:
        req = one("Include 5 tables.")
        assert req.verification_type is VerificationType.MANUAL

    def test_in_text_citations_are_unsupported(self) -> None:
        assert (
            one("Include at least 20 citations.").verification_type is VerificationType.UNSUPPORTED
        )

    def test_mention_at_least_twice(self) -> None:
        assert rule("Mention climate change at least twice.") == (
            "occurrences",
            {"text": "climate change", "min": 2},
        )

    def test_mention_at_most_n_times(self) -> None:
        assert rule('Use "risk" at most 3 times.')[1] == {"text": "risk", "max": 3}

    def test_mention_without_a_bound_is_ambiguous(self) -> None:
        assert one("Mention climate change twice.").verification_type is VerificationType.MANUAL


class TestPreservation:
    def test_quoted_text_becomes_a_rule(self) -> None:
        assert rule('Preserve the following text exactly: "What factors matter?"') == (
            "preserve_text",
            {"text": "What factors matter?"},
        )

    def test_quote_block_after_a_lead_in(self) -> None:
        result = extract_requirements(
            "Preserve the following text exactly:\n> Line one.\n> Line two.\n"
        )
        (req,) = result.requirements
        assert req.checker == "preserve_text"
        assert req.parameters == {"text": "Line one.\nLine two."}

    @pytest.mark.parametrize(
        "text",
        [
            "Do not modify the research questions.",
            "Do not rephrase the objectives.",
            "Use the title exactly as provided.",
            "Keep the abstract unchanged.",
        ],
    )
    def test_protected_text_that_was_not_supplied_cannot_be_tested(self, text: str) -> None:
        req = one(text)
        assert req.verification_type is VerificationType.MANUAL
        assert req.category is Category.PRESERVATION
        assert req.checker is None
        assert "preserve_text" in (req.notes or "")

    def test_negated_edit_with_quoted_text_is_testable(self) -> None:
        req = one('Do not change "Our mission is clarity".')
        assert req.checker == "preserve_text"
        assert req.parameters == {"text": "Our mission is clarity"}


class TestSubjectiveRequirementsAreNeverDeterministic:
    @pytest.mark.parametrize(
        "text",
        [
            "Write in an engaging scholarly manner.",
            "Make this highly engaging.",
            "Write like a master's student.",
            "Use strong academic reasoning.",
            "Use British English.",
            "Include all five research objectives.",
            "Maintain a professional tone.",
        ],
    )
    def test_semantic(self, text: str) -> None:
        req = one(text)
        assert req.verification_type is VerificationType.SEMANTIC
        assert req.checker is None
        assert req.parameters == {}

    def test_visual_requirements_are_manual(self) -> None:
        assert (
            one("Make the presentation visually appealing.").verification_type
            is VerificationType.MANUAL
        )

    @pytest.mark.parametrize("text", ["Use APA 7th referencing.", "Use Times New Roman 12pt."])
    def test_layout_and_style_guides_are_unsupported(self, text: str) -> None:
        assert one(text).verification_type is VerificationType.UNSUPPORTED


class TestStructureOfTheResult:
    def test_ids_are_sequential_and_stable(self) -> None:
        text = "Do not use em dashes.\nInclude a conclusion.\nMake it engaging."
        first = [r.id for r in extract_requirements(text).requirements]
        second = [r.id for r in extract_requirements(text).requirements]
        assert first == second == ["SG001", "SG002", "SG003"]

    def test_non_instructions_are_skipped_and_reported(self) -> None:
        result = extract_requirements("The topic is climate adaptation.\nWhat is the deadline?")
        assert result.requirements == []
        assert len(result.skipped) == 2

    def test_compound_sentence_is_split(self) -> None:
        result = extract_requirements("Do not use em dashes and do not exceed 3000 words.")
        assert [r.checker for r in result.requirements] == ["forbidden_punctuation", "word_count"]

    def test_quoted_and_inside_quotes_does_not_split(self) -> None:
        req = one('Use the heading "Questions and Answers".')
        assert req.parameters == {"headings": ["Questions and Answers"]}

    def test_abbreviations_do_not_end_sentences(self) -> None:
        result = extract_requirements("Cite sources, e.g. journals. Include a conclusion.")
        assert len(result.requirements) >= 1

    def test_source_text_and_interpretation_are_kept(self) -> None:
        result = extract_requirements("Do not use em dashes.")
        assert result.items[0].source == "Do not use em dashes"
        assert "em_dash" in result.items[0].interpretation

    def test_every_extracted_requirement_is_internally_valid(self) -> None:
        from specguard.api import validate_data
        from specguard.models.specification import Specification

        text = (FIXTURES / "instructions.txt").read_text(encoding="utf-8")
        spec = Specification(name="x", requirements=extract_requirements(text).requirements)
        assert validate_data(spec.model_dump(mode="json")).ok

    def test_empty_input(self) -> None:
        assert extract_requirements("").requirements == []


class TestSampleBrief:
    """The end-to-end example from the project brief."""

    result: ExtractionResult = extract_requirements(
        (FIXTURES / "instructions.txt").read_text(encoding="utf-8")
    )

    def test_deterministic_requirements(self) -> None:
        det = [
            (r.checker, r.parameters)
            for r in self.result.requirements
            if r.verification_type is DET
        ]
        assert det[:3] == [
            ("word_count", {"min": 1500}),
            ("word_count", {"max": 2000}),
            ("forbidden_punctuation", {"marks": ["em_dash"]}),
        ]
        headings = [p["headings"][0] for c, p in det if c == "required_section"]
        assert headings == [
            "Background",
            "Findings",
            "Recommendations",
            ["Conclusion", "Conclusions"],
        ]
        assert len(det) == 7

    def test_title_and_style_are_kept_but_not_tested(self) -> None:
        untested = [r for r in self.result.requirements if r.verification_type is not DET]
        assert [r.verification_type for r in untested] == [
            VerificationType.MANUAL,
            VerificationType.SEMANTIC,
        ]
        assert "engaging" in untested[1].description
