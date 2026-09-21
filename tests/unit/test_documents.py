"""Document extraction: txt, Markdown, DOCX, encodings, limits and malformed input."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from tests.helpers import md, txt

from specguard.errors import DocumentReadError, UnsupportedFileTypeError
from specguard.extractors import load_document, load_document_from_text, supported_extensions


class TestMarkdown:
    doc = md(
        "---\ntitle: x\n---\n# Title\n\nIntro paragraph\ncontinues here.\n\n"
        "## Section One\n\n- bullet a\n- bullet b\n1. numbered\n\n> quoted text\n\n"
        "```python\nprint('hi')\n```\n\n| h1 | h2 |\n| -- | -- |\n| c1 | c2 |\n"
    )

    def test_headings_with_levels_and_lines(self) -> None:
        assert [(h.text, h.level, h.line) for h in self.doc.headings] == [
            ("Title", 1, 4),
            ("Section One", 2, 9),
        ]

    def test_front_matter_is_metadata_not_content(self) -> None:
        assert "title: x" in self.doc.metadata["front_matter"]
        assert all("title: x" not in p.text for p in self.doc.paragraphs)

    def test_paragraph_numbers_and_start_lines(self) -> None:
        intro = next(p for p in self.doc.paragraphs if p.text.startswith("Intro"))
        assert intro.line == 6
        assert intro.text == "Intro paragraph\ncontinues here."

    def test_list_items_are_separate_and_typed(self) -> None:
        kinds = [(p.text, p.list_marker) for p in self.doc.paragraphs if p.kind == "list_item"]
        assert kinds == [("bullet a", "bullet"), ("bullet b", "bullet"), ("numbered", "numbered")]

    def test_fenced_code_is_one_block_with_language(self) -> None:
        (code,) = self.doc.code_blocks
        assert code.text == "print('hi')"
        assert code.language == "python"

    def test_pipe_table_is_parsed(self) -> None:
        (table,) = self.doc.tables
        assert table.rows == [["h1", "h2"], ["c1", "c2"]]
        assert table.row_lines == [21, 23]  # the delimiter row (line 22) is not a data row

    def test_inline_markup_is_removed_from_text(self) -> None:
        doc = md("Some **bold**, _italic_, `code` and [a link](http://x.test) here.")
        assert doc.paragraphs[0].text == "Some bold, italic, code and a link here."

    def test_snake_case_is_not_treated_as_emphasis(self) -> None:
        assert md("use snake_case_names here").paragraphs[0].text == "use snake_case_names here"

    def test_setext_headings(self) -> None:
        doc = md("Big Title\n=========\n\ntext\n\nSub Title\n---------\n\nmore")
        assert [(h.text, h.level) for h in doc.headings] == [("Big Title", 1), ("Sub Title", 2)]

    def test_thematic_break_is_not_content(self) -> None:
        doc = md("above\n\n---\n\nbelow")
        assert [p.text for p in doc.paragraphs] == ["above", "below"]

    def test_row_of_dashes_without_matching_header_is_not_a_table(self) -> None:
        assert md("a | b\n---\n").tables == []

    def test_unclosed_fence_runs_to_end_of_file(self) -> None:
        doc = md("```\ncode without end\nmore")
        assert doc.code_blocks[0].text == "code without end\nmore"

    def test_section_for_position(self) -> None:
        doc = md("# A\n\ntext a\n\n# B\n\ntext b")
        assert doc.paragraphs[1].text == "text a"
        assert doc.section_for_position(doc.paragraphs[1].position) == "A"
        assert doc.section_for_position(doc.paragraphs[3].position) == "B"


class TestPlainText:
    def test_blank_line_separates_paragraphs_and_lines_are_tracked(self) -> None:
        doc = txt("first\nsecond\n\nthird")
        assert [(p.index, p.line) for p in doc.paragraphs] == [(1, 1), (2, 4)]

    def test_all_caps_and_numbered_lines_are_headings(self) -> None:
        doc = txt("INTRODUCTION\n\nBody text here.\n\n2.1 Sub topic\n\nMore body text here.")
        assert [(h.text, h.level) for h in doc.headings] == [
            ("INTRODUCTION", 1),
            ("2.1 Sub topic", 2),
        ]

    def test_short_plain_line_is_only_a_candidate_not_a_heading(self) -> None:
        doc = txt("Conclusion\n\nSome sentence that ends here.")
        assert doc.headings == []
        assert doc.paragraphs[0].heading_candidate

    def test_sentence_is_never_a_candidate(self) -> None:
        assert not txt("This is a full sentence.").paragraphs[0].heading_candidate

    def test_crlf_is_normalised(self) -> None:
        assert txt("a\r\nb\r\n\r\nc").paragraphs[0].text == "a\nb"


class TestReadingFiles:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(DocumentReadError, match="not found"):
            load_document(tmp_path / "nope.md")

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "x.pdf"
        f.write_bytes(b"%PDF")
        with pytest.raises(UnsupportedFileTypeError, match=r"\.pdf"):
            load_document(f)

    def test_supported_types(self) -> None:
        assert {".txt", ".md", ".docx"} <= set(supported_extensions())

    def test_directory_is_not_a_file(self, tmp_path: Path) -> None:
        d = tmp_path / "folder.md"
        d.mkdir()
        with pytest.raises(DocumentReadError, match="Not a regular file"):
            load_document(d)

    def test_size_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 100, encoding="utf-8")
        with pytest.raises(DocumentReadError, match="limit"):
            load_document(f, max_bytes=50)

    def test_utf8_bom_is_stripped(self, tmp_path: Path) -> None:
        f = tmp_path / "bom.txt"
        f.write_bytes(b"\xef\xbb\xbfhello")
        assert load_document(f).paragraphs[0].text == "hello"

    def test_windows_1252_fallback_is_recorded(self, tmp_path: Path) -> None:
        f = tmp_path / "old.txt"
        f.write_bytes("caf\xe9".encode("cp1252"))
        doc = load_document(f)
        assert doc.paragraphs[0].text == "café"
        assert doc.metadata["encoding"] == "cp1252"

    def test_utf16_with_bom(self, tmp_path: Path) -> None:
        f = tmp_path / "u16.txt"
        f.write_text("hello world", encoding="utf-16")
        assert load_document(f).paragraphs[0].text == "hello world"

    def test_binary_content_is_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "bin.txt"
        f.write_bytes(b"abc\x00\x01\x02def")
        with pytest.raises(DocumentReadError, match="binary"):
            load_document(f)

    def test_in_memory_text_type_is_restricted(self) -> None:
        with pytest.raises(UnsupportedFileTypeError):
            load_document_from_text("x", "docx")

    def test_documents_are_never_modified(self, tmp_path: Path) -> None:
        f = tmp_path / "keep.md"
        f.write_text("# A\n\ntext\n", encoding="utf-8")
        before = (f.read_bytes(), f.stat().st_mtime_ns)
        load_document(f)
        assert (f.read_bytes(), f.stat().st_mtime_ns) == before


class TestDocx:
    def test_headings_levels_and_title(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        assert [(h.text, h.level) for h in doc.headings] == [
            ("Clinic Attendance Study", 1),
            ("Introduction", 1),
            ("Methodology", 1),
            ("Data sources", 2),
            ("Conclusion", 1),
            ("References", 1),
        ]

    def test_paragraph_numbers_count_non_empty_paragraphs_in_order(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        assert doc.paragraphs[0].text == "Clinic Attendance Study"
        assert [p.index for p in doc.paragraphs] == list(range(1, len(doc.paragraphs) + 1))
        assert doc.paragraphs[0].line is None  # DOCX has no source lines

    def test_list_items_are_detected_as_bullets(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        assert [p.text for p in doc.paragraphs if p.list_marker == "bullet"] == [
            "Interviews were recorded and transcribed.",
            "Records were double checked.",
        ]

    def test_table_cells_are_extracted(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        (table,) = doc.tables
        assert table.rows[1] == ["North", "120", "TBD figure"]

    def test_table_cell_locations(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        (unit,) = [u for u in doc.units() if "TBD" in u.text]
        assert (unit.location.table, unit.location.row, unit.location.column) == (1, 2, 3)

    def test_section_metadata_and_defaults(self, tmp_path: Path) -> None:
        from tests.helpers import build_docx

        doc = load_document(
            build_docx(
                tmp_path / "f.docx", landscape=True, margin_cm=2.0, font="Arial", font_size=12
            )
        )
        section = doc.metadata["sections"][0]
        assert section["orientation"] == "landscape"
        assert section["margin_left_cm"] == 2.0
        assert doc.metadata["default_font_name"] == "Arial"
        assert doc.metadata["default_font_size_pt"] == 12.0

    def test_section_under_heading(self, thesis_docx: Path) -> None:
        doc = load_document(thesis_docx)
        (heading,) = doc.find_headings(["References"])
        assert [p.text[:6] for p in doc.body_paragraphs_under(heading)] == ["Adeyem", "Okafor"]

    def test_not_a_zip(self, tmp_path: Path) -> None:
        f = tmp_path / "fake.docx"
        f.write_bytes(b"this is not a zip file")
        with pytest.raises(DocumentReadError, match=r"not a valid \.docx"):
            load_document(f)

    def test_zip_that_is_not_word(self, tmp_path: Path) -> None:
        f = tmp_path / "other.docx"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("hello.txt", "hi")
        with pytest.raises(DocumentReadError, match="not a Word document"):
            load_document(f)

    def test_truncated_docx(self, thesis_docx: Path, tmp_path: Path) -> None:
        f = tmp_path / "cut.docx"
        f.write_bytes(thesis_docx.read_bytes()[:300])
        with pytest.raises(DocumentReadError):
            load_document(f)

    def test_corrupt_document_xml(self, tmp_path: Path) -> None:
        f = tmp_path / "corrupt.docx"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("word/document.xml", "<not-xml")
            zf.writestr("[Content_Types].xml", "<Types/>")
        f.write_bytes(buffer.getvalue())
        with pytest.raises(DocumentReadError):
            load_document(f)

    def test_archive_that_expands_too_much_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from specguard.extractors import docx as docx_extractor

        monkeypatch.setattr(docx_extractor, "MAX_UNCOMPRESSED_BYTES", 10)
        f = tmp_path / "big.docx"
        with zipfile.ZipFile(f, "w") as zf:
            zf.writestr("word/document.xml", "<w/>" * 50)
        with pytest.raises(DocumentReadError, match="unreasonable size"):
            load_document(f)
