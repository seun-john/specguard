"""Common in-memory representation of an audited document."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from specguard.models.result import Location
from specguard.utils.text import make_excerpt, normalize_heading


@dataclass
class Paragraph:
    """One block of text.

    `text` is plain text: Markdown markers, list bullets and heading hashes are removed.
    `line` is the 1-based source line where the block starts (None for DOCX).
    `index` is the 1-based paragraph number and `position` orders all body blocks,
    including tables, so sections can be computed.
    """

    index: int
    text: str
    position: int
    line: int | None = None
    kind: str = "paragraph"  # paragraph | heading | list_item | code | quote
    heading_level: int | None = None
    list_marker: str | None = None  # bullet | numbered | unknown
    style: str | None = None
    heading_candidate: bool = False  # plain-text line that looks like an unformatted heading
    language: str | None = None  # for code blocks


@dataclass
class Heading:
    """A heading, with the position of its paragraph."""

    text: str
    level: int
    paragraph: int
    position: int
    line: int | None = None

    @property
    def normalized(self) -> str:
        return normalize_heading(self.text)


@dataclass
class Table:
    """A table. `rows` holds cell text; `position` orders it among body blocks."""

    index: int
    rows: list[list[str]]
    position: int
    line: int | None = None
    row_lines: list[int | None] = field(default_factory=list)  # source line of each row


@dataclass
class TextUnit:
    """A searchable piece of text (paragraph or table cell) with its location."""

    text: str
    location: Location
    kind: str
    position: int

    @property
    def flat(self) -> str:
        """Text with newlines turned into spaces (same length), so phrases can span wraps."""
        return self.text.replace("\n", " ")

    def locate(self, start: int, end: int) -> Location:
        """The location of a match at [start, end) within this unit."""
        loc = self.location.model_copy()
        if loc.line is not None:
            loc.line += self.text.count("\n", 0, start)
        loc.excerpt = make_excerpt(self.text, start, end)
        return loc


@dataclass
class Document:
    """A parsed document: paragraphs, headings, tables and format-specific metadata."""

    file_type: str  # txt | md | docx
    raw_text: str
    paragraphs: list[Paragraph] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    path: str | None = None
    size_bytes: int | None = None

    # -- structure ---------------------------------------------------------------------

    def section_for_position(self, position: int) -> str | None:
        """Text of the nearest heading at or before a body position."""
        current: str | None = None
        for heading in self.headings:
            if heading.position <= position:
                current = heading.text
            else:
                break
        return current

    def section_span(self, heading: Heading) -> tuple[int, int]:
        """Body positions covered by a heading's section: [start, end)."""
        end = 10**9
        for other in self.headings:
            if other.position > heading.position and other.level <= heading.level:
                end = other.position
                break
        return heading.position, end

    def find_headings(self, names: list[str], *, exact: bool = True) -> list[Heading]:
        """Headings whose normalized text matches any of the names."""
        wanted = [normalize_heading(n) for n in names]
        found = []
        for heading in self.headings:
            norm = heading.normalized
            if any((norm == w) if exact else (w in norm) for w in wanted):
                found.append(heading)
        return found

    def body_paragraphs_under(self, heading: Heading) -> list[Paragraph]:
        """Non-heading paragraphs inside a heading's section."""
        start, end = self.section_span(heading)
        return [
            p
            for p in self.paragraphs
            if start < p.position < end and p.kind != "heading" and p.text.strip()
        ]

    @property
    def code_blocks(self) -> list[Paragraph]:
        return [p for p in self.paragraphs if p.kind == "code"]

    # -- text access -------------------------------------------------------------------

    def units(
        self,
        *,
        include_headings: bool = True,
        include_tables: bool = True,
        exclude_positions: list[tuple[int, int]] | None = None,
    ) -> Iterator[TextUnit]:
        """Yield every searchable text unit in document order."""
        skip = exclude_positions or []

        def excluded(pos: int) -> bool:
            return any(lo <= pos < hi for lo, hi in skip)

        entries: list[tuple[int, TextUnit]] = []
        for p in self.paragraphs:
            if not include_headings and p.kind == "heading":
                continue
            if excluded(p.position) or not p.text.strip():
                continue
            loc = Location(
                line=p.line, paragraph=p.index, heading=self.section_for_position(p.position)
            )
            entries.append((p.position, TextUnit(p.text, loc, p.kind, p.position)))
        if include_tables:
            for t in self.tables:
                if excluded(t.position):
                    continue
                section = self.section_for_position(t.position)
                for r, row in enumerate(t.rows, start=1):
                    for c, cell in enumerate(row, start=1):
                        if not cell.strip():
                            continue
                        line = t.row_lines[r - 1] if r - 1 < len(t.row_lines) else t.line
                        loc = Location(line=line, table=t.index, row=r, column=c, heading=section)
                        entries.append((t.position, TextUnit(cell, loc, "table_cell", t.position)))
        entries.sort(key=lambda e: e[0])  # stable: cells stay in row/column order
        for _, unit in entries:
            yield unit

    def text(self, **kwargs: Any) -> str:
        """All unit text joined with blank lines. Accepts the same options as `units`."""
        return "\n\n".join(u.text for u in self.units(**kwargs))
