"""Extractor interface and registry.

An extractor turns the bytes of one file format into a `Document`. Adding PDF, PPTX or
HTML support later means writing one class and registering it; nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from specguard.errors import DocumentReadError, UnsupportedFileTypeError
from specguard.models.document import Document
from specguard.utils.paths import MAX_DOCUMENT_BYTES, read_bytes_limited


class DocumentExtractor(ABC):
    """Parses one file format into a Document."""

    file_type: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]

    @abstractmethod
    def extract(self, data: bytes, source: str) -> Document:
        """Parse `data`. `source` names the file in error messages. Raise DocumentReadError."""


_EXTRACTORS: dict[str, DocumentExtractor] = {}


def register_extractor(extractor: DocumentExtractor) -> None:
    """Register an extractor for each of its file extensions."""
    for ext in extractor.extensions:
        _EXTRACTORS[ext.lower()] = extractor


def supported_extensions() -> list[str]:
    return sorted(_EXTRACTORS)


def extractor_for_extension(extension: str) -> DocumentExtractor:
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    try:
        return _EXTRACTORS[ext]
    except KeyError:
        supported = ", ".join(supported_extensions())
        raise UnsupportedFileTypeError(
            f"Unsupported file type '{ext}'. Supported types: {supported}"
        ) from None


def load_document(path: str | Path, *, max_bytes: int = MAX_DOCUMENT_BYTES) -> Document:
    """Read and parse a file. The file is never modified."""
    p = Path(path)
    extractor = extractor_for_extension(p.suffix)  # fail fast on type before reading
    data = read_bytes_limited(p, max_bytes)
    try:
        doc = extractor.extract(data, str(p))
    except DocumentReadError:
        raise
    except Exception as exc:  # parser bugs must not leak as tracebacks
        raise DocumentReadError(f"Could not parse {p}: {type(exc).__name__}") from exc
    doc.path = str(p)
    doc.size_bytes = len(data)
    return doc


def load_document_from_text(content: str, file_type: str = "txt") -> Document:
    """Parse in-memory text as `txt` or `md` (used by the MCP server and tests)."""
    if file_type.lower().lstrip(".") not in ("txt", "md", "markdown", "text"):
        raise UnsupportedFileTypeError(f"In-memory content can be 'txt' or 'md', not '{file_type}'")
    ext = ".md" if file_type.lower().lstrip(".") in ("md", "markdown") else ".txt"
    doc = extractor_for_extension(ext).extract(content.encode("utf-8"), "<text>")
    doc.size_bytes = len(content.encode("utf-8"))
    return doc
