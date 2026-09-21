"""Document extractors. Importing this package registers the built-in formats."""

from specguard.extractors import docx as _docx  # noqa: F401  (registers .docx)
from specguard.extractors import markdown as _markdown  # noqa: F401  (registers .md)
from specguard.extractors import text as _text  # noqa: F401  (registers .txt)
from specguard.extractors.base import (
    DocumentExtractor,
    extractor_for_extension,
    load_document,
    load_document_from_text,
    register_extractor,
    supported_extensions,
)

__all__ = [
    "DocumentExtractor",
    "extractor_for_extension",
    "load_document",
    "load_document_from_text",
    "register_extractor",
    "supported_extensions",
]
