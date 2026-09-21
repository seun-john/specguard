"""Line-based parser shared by the plain-text and Markdown extractors.

It is deliberately small: it finds paragraphs, headings, list items, fenced code, quotes
and pipe tables, and records source line numbers. It is not a full CommonMark parser.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from specguard.extractors.base import DocumentExtractor, register_extractor
from specguard.models.document import Document, Heading, Paragraph, Table
from specguard.utils.paths import decode_text

_ATX_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_RULE_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*([\w+#.-]*)")
_LIST_RE = re.compile(r"^[ \t]*(?:([-*+•])|(\d{1,3}[.)]))[ \t]+(\S.*)$")
_QUOTE_RE = re.compile(r"^ {0,3}>[ \t]?(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
_TERMINAL_PUNCT = ".,;!?"


def _is_block_start(line: str, markdown: bool) -> bool:
    """True if this line begins a new block even without a preceding blank line."""
    if _ATX_RE.match(line) or _LIST_RE.match(line):
        return True
    if markdown and (_FENCE_RE.match(line) or _QUOTE_RE.match(line)):
        return True
    return bool(_RULE_RE.match(line))


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _plain_heading_level(text: str) -> int | None:
    """Guess a plain-text heading level from numbering or ALL CAPS, else None."""
    words = text.split()
    if not words or len(words) > 10 or len(text) > 80 or text[-1] in _TERMINAL_PUNCT + ":":
        return None
    m = _NUMBERED_HEADING_RE.match(text)
    if m:
        return m.group(1).count(".") + 1
    letters = [c for c in text if c.isalpha()]
    if len(letters) >= 3 and text.upper() == text:
        return 1
    return None


def parse_lines(
    raw: str,
    *,
    file_type: str,
    markdown: bool,
    inline: Callable[[str], str] = lambda s: s,
) -> Document:
    """Parse text into a Document. `inline` cleans inline markup (identity for txt)."""
    lines = raw.split("\n")
    n = len(lines)
    doc = Document(file_type=file_type, raw_text=raw)
    position = 0
    para_index = 0
    i = 0

    def add_paragraph(text: str, line: int, **kw: object) -> Paragraph:
        nonlocal position, para_index
        position += 1
        para_index += 1
        p = Paragraph(index=para_index, text=text, position=position, line=line, **kw)  # type: ignore[arg-type]
        doc.paragraphs.append(p)
        if p.kind == "heading":
            assert p.heading_level is not None
            doc.headings.append(
                Heading(
                    text=p.text,
                    level=p.heading_level,
                    paragraph=p.index,
                    position=p.position,
                    line=p.line,
                )
            )
        return p

    if markdown and lines and lines[0].strip() == "---":
        for j in range(1, min(n, 200)):
            if lines[j].strip() in ("---", "..."):
                doc.metadata["front_matter"] = "\n".join(lines[1:j])
                i = j + 1
                break

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        fence = _FENCE_RE.match(line) if markdown else None
        if fence:
            marker, lang = fence.group(1), fence.group(2)
            start = i
            i += 1
            body: list[str] = []
            while i < n and not (
                lines[i].strip().startswith(marker[0] * len(marker))
                and set(lines[i].strip()) == {marker[0]}
            ):
                body.append(lines[i])
                i += 1
            i += 1  # closing fence (or end of file)
            add_paragraph("\n".join(body), start + 1, kind="code", language=lang or None)
            continue

        atx = _ATX_RE.match(line)
        if atx:
            add_paragraph(
                inline(atx.group(2)), i + 1, kind="heading", heading_level=len(atx.group(1))
            )
            i += 1
            continue

        if _RULE_RE.match(line):
            i += 1
            continue

        if (
            markdown
            and "|" in line
            and i + 1 < n
            and _TABLE_SEP_RE.match(lines[i + 1])
            and len(_split_row(lines[i + 1])) == len(_split_row(line))
        ):
            start = i
            rows: list[list[str]] = [[inline(c) for c in _split_row(line)]]
            row_lines: list[int | None] = [i + 1]
            i += 2
            while i < n and lines[i].strip() and "|" in lines[i]:
                rows.append([inline(c) for c in _split_row(lines[i])])
                row_lines.append(i + 1)
                i += 1
            position += 1
            doc.tables.append(
                Table(
                    index=len(doc.tables) + 1,
                    rows=rows,
                    position=position,
                    line=start + 1,
                    row_lines=row_lines,
                )
            )
            continue

        lm = _LIST_RE.match(line)
        if lm:
            start = i
            marker_kind = "bullet" if lm.group(1) else "numbered"
            parts = [lm.group(3)]
            i += 1
            while i < n and lines[i].strip() and not _is_block_start(lines[i], markdown):
                parts.append(lines[i].strip())
                i += 1
            add_paragraph(
                inline("\n".join(parts)), start + 1, kind="list_item", list_marker=marker_kind
            )
            continue

        quote = _QUOTE_RE.match(line) if markdown else None
        if quote:
            start = i
            parts = []
            while i < n and (qm := _QUOTE_RE.match(lines[i])):
                parts.append(qm.group(1))
                i += 1
            add_paragraph(inline("\n".join(parts).strip()), start + 1, kind="quote")
            continue

        # Ordinary paragraph, or a setext heading if an underline follows.
        start = i
        parts = [line.strip()]
        i += 1
        setext_level: int | None = None
        while i < n and lines[i].strip():
            sm = _SETEXT_RE.match(lines[i])
            if sm:
                setext_level = 1 if sm.group(1).startswith("=") else 2
                i += 1
                break
            if _is_block_start(lines[i], markdown):
                break
            parts.append(lines[i].strip())
            i += 1
        text = inline("\n".join(parts))
        if setext_level is not None:
            add_paragraph(text, start + 1, kind="heading", heading_level=setext_level)
            continue

        if not markdown and len(parts) == 1:
            level = _plain_heading_level(text)
            if level is not None:
                add_paragraph(text, start + 1, kind="heading", heading_level=level)
                continue
            words = text.split()
            candidate = len(words) <= 10 and len(text) <= 80 and text[-1] not in _TERMINAL_PUNCT
            add_paragraph(text, start + 1, heading_candidate=candidate)
            continue
        add_paragraph(text, start + 1)

    doc.metadata["line_count"] = n
    return doc


class PlainTextExtractor(DocumentExtractor):
    """`.txt` files. Headings are recognised from `#`, underlines, numbering and ALL CAPS."""

    file_type = "txt"
    extensions = (".txt", ".text")

    def extract(self, data: bytes, source: str) -> Document:
        raw, encoding = decode_text(data, source)
        doc = parse_lines(raw, file_type="txt", markdown=False)
        doc.metadata["encoding"] = encoding
        return doc


register_extractor(PlainTextExtractor())
