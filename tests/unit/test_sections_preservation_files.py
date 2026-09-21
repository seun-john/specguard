"""required_section, preserve_text, file_type and docx_format."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.helpers import FIXTURES, build_docx, md, run_rule, txt

from specguard.extractors import load_document
from specguard.models.result import Status
from specguard.rules import default_registry


class TestRequiredSection:
    doc = md("# Introduction\n\ntext\n\n## 2.1 Methods\n\ntext\n\n# Conclusions\n\ntext\n")

    def test_markdown_headings_found(self) -> None:
        result = run_rule(self.doc, "required_section", {"headings": ["Introduction"]})
        assert result.status is Status.PASS
        assert result.locations[0].line == 1

    def test_missing_heading_fails_and_lists_what_exists(self) -> None:
        result = run_rule(self.doc, "required_section", {"headings": ["Recommendations"]})
        assert result.status is Status.FAIL
        assert result.details["missing"] == ["Recommendations"]
        assert any("Headings in document" in e and "Introduction" in e for e in result.evidence)

    def test_case_insensitive_by_default(self) -> None:
        assert (
            run_rule(self.doc, "required_section", {"headings": ["INTRODUCTION"]}).status
            is Status.PASS
        )

    def test_case_sensitive_mode(self) -> None:
        params = {"headings": ["INTRODUCTION"], "case_sensitive": True}
        assert run_rule(self.doc, "required_section", params).status is Status.FAIL

    def test_numbering_is_ignored_in_exact_mode(self) -> None:
        assert (
            run_rule(self.doc, "required_section", {"headings": ["Methods"]}).status is Status.PASS
        )

    def test_exact_mode_rejects_partial_matches(self) -> None:
        assert (
            run_rule(self.doc, "required_section", {"headings": ["Method"]}).status is Status.FAIL
        )

    def test_contains_mode(self) -> None:
        params = {"headings": ["Method"], "exact": False}
        assert run_rule(self.doc, "required_section", params).status is Status.PASS

    def test_alternatives(self) -> None:
        params = {"headings": [["Conclusion", "Conclusions"]]}
        assert run_rule(self.doc, "required_section", params).status is Status.PASS
        assert (
            run_rule(self.doc, "required_section", {"headings": [["Summary", "Overview"]]}).status
            is Status.FAIL
        )

    def test_require_any(self) -> None:
        params = {"headings": ["Introduction", "Appendix"], "require": "any"}
        assert run_rule(self.doc, "required_section", params).status is Status.PASS

    def test_one_missing_of_several_fails(self) -> None:
        result = run_rule(self.doc, "required_section", {"headings": ["Introduction", "Appendix"]})
        assert result.status is Status.FAIL

    def test_near_miss_is_suggested(self) -> None:
        result = run_rule(self.doc, "required_section", {"headings": ["Conclusion"]})
        assert result.status is Status.FAIL
        assert any('close to existing heading "Conclusions"' in e for e in result.evidence)

    def test_bold_text_that_is_not_a_heading_does_not_count(self) -> None:
        result = run_rule(
            md("**Conclusion**\n\nbody"), "required_section", {"headings": ["Conclusion"]}
        )
        assert result.status is Status.FAIL

    def test_plain_text_standalone_line_is_accepted_with_a_caveat(self) -> None:
        result = run_rule(
            txt("Conclusion\n\nSome closing text here."),
            "required_section",
            {"headings": ["Conclusion"]},
        )
        assert result.status is Status.PASS
        assert result.confidence < 1.0
        assert any("not a formatted heading" in e for e in result.evidence)

    def test_plain_text_sentence_is_not_a_heading(self) -> None:
        result = run_rule(
            txt("In conclusion we agree.\n\nMore."),
            "required_section",
            {"headings": ["Conclusion"]},
        )
        assert result.status is Status.FAIL

    def test_docx_heading_styles(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        result = run_rule(
            doc, "required_section", {"headings": ["Introduction", "Methodology", "Conclusion"]}
        )
        assert result.status is Status.PASS
        assert (
            run_rule(doc, "required_section", {"headings": ["Recommendations"]}).status
            is Status.FAIL
        )

    def test_docx_paragraph_that_only_looks_like_a_heading_fails(self, tmp_path: Path) -> None:
        import docx

        d = docx.Document()
        d.add_paragraph("Conclusion")  # Normal style, not a heading
        d.save(str(tmp_path / "n.docx"))
        result = run_rule(
            load_document(tmp_path / "n.docx"), "required_section", {"headings": ["Conclusion"]}
        )
        assert result.status is Status.FAIL

    def test_no_headings_at_all(self) -> None:
        result = run_rule(md("just text"), "required_section", {"headings": ["Intro"]})
        assert result.status is Status.FAIL
        assert any("(none found)" in e for e in result.evidence)


class TestPreservation:
    QUESTION = "What factors are associated with clinic attendance?"

    def test_exact_preservation_passes(self) -> None:
        doc = md(f"# Q\n\n{self.QUESTION}\n\nMore text.")
        result = run_rule(doc, "preserve_text", {"text": self.QUESTION})
        assert result.status is Status.PASS
        assert result.locations[0].paragraph == 2

    def test_minor_change_fails_with_expected_found_and_diff(self) -> None:
        doc = md("What are the major factors associated with clinic attendance?")
        result = run_rule(doc, "preserve_text", {"text": self.QUESTION})
        assert result.status is Status.FAIL
        assert result.message.startswith("Protected text was modified")
        assert result.expected == self.QUESTION
        assert result.actual == "What are the major factors associated with clinic attendance?"
        joined = "\n".join(result.evidence)
        assert "[-factors-]" not in joined  # 'factors' was kept
        assert "{+are the major+}" in joined
        assert result.locations[0].paragraph == 1

    def test_missing_text_says_nothing_similar(self) -> None:
        result = run_rule(
            txt("Completely unrelated content."), "preserve_text", {"text": self.QUESTION}
        )
        assert result.status is Status.FAIL
        assert result.details["missing"] == 1
        assert result.actual == "(not found)"

    def test_near_match_inside_a_longer_paragraph(self) -> None:
        doc = txt(
            f"Intro sentence here. {self.QUESTION.replace('factors', 'drivers')} Closing sentence."
        )
        result = run_rule(doc, "preserve_text", {"text": self.QUESTION})
        assert result.status is Status.FAIL
        assert "drivers" in (result.actual or "")

    def test_exact_text_inside_longer_paragraph_passes(self) -> None:
        doc = txt(f"Before. {self.QUESTION} After.")
        assert run_rule(doc, "preserve_text", {"text": self.QUESTION}).status is Status.PASS

    def test_case_change_fails_by_default_but_can_be_allowed(self) -> None:
        doc = txt(self.QUESTION.upper())
        assert run_rule(doc, "preserve_text", {"text": self.QUESTION}).status is Status.FAIL
        assert (
            run_rule(doc, "preserve_text", {"text": self.QUESTION, "case_sensitive": False}).status
            is Status.PASS
        )

    def test_whitespace_differences_are_ignored_by_default(self) -> None:
        doc = txt("What factors  are associated\nwith clinic attendance?")
        assert run_rule(doc, "preserve_text", {"text": self.QUESTION}).status is Status.PASS
        strict = {"text": self.QUESTION, "normalize_whitespace": False}
        assert run_rule(doc, "preserve_text", strict).status is Status.FAIL

    def test_curly_quotes_are_a_change_unless_normalised(self) -> None:
        doc = txt("It’s here")
        assert run_rule(doc, "preserve_text", {"text": "It's here"}).status is Status.FAIL
        assert (
            run_rule(doc, "preserve_text", {"text": "It's here", "normalize_quotes": True}).status
            is Status.PASS
        )

    def test_baseline_file_lines_each_must_survive(self) -> None:
        good = load_document(FIXTURES / "compliant_report.md")
        bad = load_document(FIXTURES / "noncompliant_report.md")
        params = {"baseline_file": "protected_questions.txt"}
        assert run_rule(good, "preserve_text", params, base_dir=FIXTURES).status is Status.PASS
        result = run_rule(bad, "preserve_text", params, base_dir=FIXTURES)
        assert result.status is Status.FAIL
        assert result.details == {"items": 2, "changed": 1, "missing": 0}

    def test_baseline_file_split_paragraphs(self, tmp_path: Path) -> None:
        (tmp_path / "b.txt").write_text("Line one\ncontinues.\n\nSecond block.\n", encoding="utf-8")
        doc = txt("Line one\ncontinues.\n\nSecond block.")
        params = {"baseline_file": "b.txt", "split": "paragraphs"}
        assert run_rule(doc, "preserve_text", params, base_dir=tmp_path).status is Status.PASS

    def test_baseline_outside_spec_folder_is_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        inner = tmp_path / "spec"
        inner.mkdir()
        checker = default_registry.create("preserve_text", _ctx(inner))
        (problem,) = checker.validate_parameters({"baseline_file": "../secret.txt"})
        assert "inside the specification's folder" in problem

    def test_baseline_file_without_a_folder_is_refused(self) -> None:
        checker = default_registry.create("preserve_text")
        (problem,) = checker.validate_parameters({"baseline_file": "x.txt"})
        assert "specification file location" in problem

    def test_missing_baseline_file_is_a_validation_problem(self, tmp_path: Path) -> None:
        checker = default_registry.create("preserve_text", _ctx(tmp_path))
        (problem,) = checker.validate_parameters({"baseline_file": "absent.txt"})
        assert "cannot read baseline_file" in problem

    def test_requires_some_protected_text(self) -> None:
        assert default_registry.create("preserve_text").validate_parameters({})

    def test_table_text_is_searched_too(self) -> None:
        doc = md("| Q |\n| - |\n| What factors are associated with clinic attendance? |\n")
        assert run_rule(doc, "preserve_text", {"text": self.QUESTION}).status is Status.PASS


def _ctx(base: Path):  # type: ignore[no-untyped-def]
    from specguard.rules import AuditContext

    return AuditContext(base_dir=base)


class TestFileType:
    def test_matching_extension_passes(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        assert run_rule(doc, "file_type", {"extensions": ["docx"]}).status is Status.PASS
        assert run_rule(doc, "file_type", {"extensions": [".docx", "md"]}).status is Status.PASS

    def test_wrong_extension_fails(self, thesis_docx: Path) -> None:
        result = run_rule(load_document(thesis_docx), "file_type", {"extension": "md"})
        assert result.status is Status.FAIL
        assert result.actual == ".docx"

    def test_markdown_alias(self) -> None:
        assert run_rule(md("x"), "file_type", {"extensions": ["markdown"]}).status is Status.PASS

    def test_in_memory_document_uses_its_type(self) -> None:
        assert run_rule(txt("x"), "file_type", {"extensions": ["txt"]}).status is Status.PASS


class TestDocxFormat:
    def test_margins_orientation_font(self, tmp_path: Path) -> None:
        doc = load_document(
            build_docx(tmp_path / "a.docx", margin_cm=2.54, font="Arial", font_size=12)
        )
        params = {
            "margin_cm": 2.54,
            "orientation": "portrait",
            "font_name": "arial",
            "font_size_pt": 12,
        }
        assert run_rule(doc, "docx_format", params).status is Status.PASS

    def test_wrong_margin_fails_with_evidence(self, tmp_path: Path) -> None:
        doc = load_document(build_docx(tmp_path / "a.docx", margin_cm=1.0))
        result = run_rule(doc, "docx_format", {"margins_cm": {"left": 2.54}})
        assert result.status is Status.FAIL
        assert any("MISMATCH section 1 left margin: 1.0 cm" in e for e in result.evidence)

    def test_landscape_detected(self, tmp_path: Path) -> None:
        doc = load_document(build_docx(tmp_path / "a.docx", landscape=True))
        assert run_rule(doc, "docx_format", {"orientation": "portrait"}).status is Status.FAIL

    def test_inherited_font_is_unverified_not_pass(self, tmp_path: Path) -> None:
        doc = load_document(build_docx(tmp_path / "a.docx"))
        doc.metadata["default_font_name"] = None
        assert run_rule(doc, "docx_format", {"font_name": "Arial"}).status is Status.UNVERIFIED

    def test_not_applicable_to_markdown(self) -> None:
        assert (
            run_rule(md("x"), "docx_format", {"orientation": "portrait"}).status
            is Status.UNVERIFIED
        )

    @pytest.mark.parametrize(
        "params", [{}, {"orientation": "sideways"}, {"margins_cm": {"middle": 1}}]
    )
    def test_invalid_parameters(self, params: dict[str, object]) -> None:
        assert default_registry.create("docx_format").validate_parameters(params)
