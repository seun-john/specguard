"""Markdown extractor: line-based structure plus inline markup removal."""

from __future__ import annotations

import re

from specguard.extractors.base import DocumentExtractor, register_extractor
from specguard.extractors.text import parse_lines
from specguard.models.document import Document
from specguard.utils.paths import decode_text

_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
_CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")
_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"\*(?=\S)(.+?)(?<=\S)\*", re.DOTALL)
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<![\w])_(?=\S)(.+?)(?<=\S)_(?![\w])", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_inline(text: str) -> str:
    """Remove inline Markdown markers, keeping the visible text.

    Newlines are preserved so line numbers computed inside a paragraph stay accurate.
    """
    text = _HTML_COMMENT_RE.sub("", text)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _AUTOLINK_RE.sub(r"\1", text)
    text = _CODE_SPAN_RE.sub(r"\2", text)
    text = _BOLD_RE.sub(r"\2", text)
    text = _STRIKE_RE.sub(r"\1", text)
    text = _ITALIC_STAR_RE.sub(r"\1", text)
    return _ITALIC_UNDERSCORE_RE.sub(r"\1", text)


class MarkdownExtractor(DocumentExtractor):
    """`.md` and `.markdown` files."""

    file_type = "md"
    extensions = (".md", ".markdown")

    def extract(self, data: bytes, source: str) -> Document:
        raw, encoding = decode_text(data, source)
        doc = parse_lines(raw, file_type="md", markdown=True, inline=strip_inline)
        doc.metadata["encoding"] = encoding
        return doc


register_extractor(MarkdownExtractor())
