"""Exception types raised by the core library."""

from __future__ import annotations


class SpecGuardError(Exception):
    """Base class for expected, user-facing errors."""


class FileAccessError(SpecGuardError):
    """A file could not be read: missing, too large, unreadable or malformed."""


class DocumentReadError(FileAccessError):
    """The document being audited could not be read or parsed."""


class UnsupportedFileTypeError(DocumentReadError):
    """No extractor is registered for this file extension."""


class PathNotAllowedError(SpecGuardError):
    """A path resolved outside the directories the caller allowed."""
