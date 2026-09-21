"""Path and file-size guards for reading untrusted locations."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from specguard.errors import DocumentReadError, PathNotAllowedError

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_SPEC_BYTES = 1024 * 1024
MAX_BASELINE_BYTES = 5 * 1024 * 1024


def is_within(path: Path, root: Path) -> bool:
    """True if `path` is `root` or inside it, after resolving symlinks and `..`."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_within(path: str | Path, roots: Sequence[Path]) -> Path:
    """Resolve `path` and require it to sit inside one of `roots`.

    A relative path is interpreted against the first root. Raises PathNotAllowedError
    if the resolved path escapes every root (for example through `..` or a symlink).
    """
    candidate = Path(path)
    if not candidate.is_absolute() and roots:
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    if roots and not any(is_within(resolved, r) for r in roots):
        allowed = ", ".join(str(r) for r in roots)
        raise PathNotAllowedError(f"{path} is outside the allowed directories ({allowed})")
    return resolved


def read_bytes_limited(path: Path, max_bytes: int) -> bytes:
    """Read a file, refusing anything larger than `max_bytes`."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise DocumentReadError(f"File not found: {path}") from None
    except OSError as exc:
        raise DocumentReadError(f"Cannot access {path}: {exc.strerror or exc}") from exc
    if not path.is_file():
        raise DocumentReadError(f"Not a regular file: {path}")
    if size > max_bytes:
        raise DocumentReadError(f"{path} is {size:,} bytes; the limit is {max_bytes:,} bytes")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise DocumentReadError(f"Cannot read {path}: {exc.strerror or exc}") from exc


def decode_text(data: bytes, source: str = "file") -> tuple[str, str]:
    """Decode bytes to text. Returns (text, encoding-used).

    Tries UTF-8 (with or without BOM), then UTF-16 when a BOM is present, then
    Windows-1252 as a documented last resort. Binary data is rejected.
    """
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise DocumentReadError(f"{source} looks like a binary file, not text")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16").replace("\r\n", "\n").replace("\r", "\n"), "utf-16"
        except UnicodeDecodeError as exc:
            raise DocumentReadError(f"{source} has a UTF-16 BOM but is not valid UTF-16") from exc
    try:
        text, encoding = data.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        try:
            text, encoding = data.decode("cp1252"), "cp1252"
        except UnicodeDecodeError as exc:
            raise DocumentReadError(f"{source} is not valid UTF-8 or Windows-1252 text") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding
