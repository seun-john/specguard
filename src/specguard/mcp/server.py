"""SpecGuard MCP server (official `mcp` Python SDK v2, `MCPServer` API).

Every tool calls `specguard.api`, the same core the CLI uses; no audit logic lives here.
Tools return plain structured data. Failures are returned as `{"ok": false, "error": ...}`
so a model can read the reason and correct its input.

File access is restricted to the `roots` given at start-up. Nothing is written and no
document text leaves the machine.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from specguard import __version__, api
from specguard.errors import FileAccessError, PathNotAllowedError, SpecGuardError
from specguard.models.specification import SpecificationError
from specguard.reports import report_to_dict
from specguard.utils.paths import resolve_within

log = logging.getLogger(__name__)

INSTRUCTIONS = (
    "SpecGuard tests whether a document followed its instructions. It reports PASS, FAIL, "
    "WARNING, UNVERIFIED or ERROR with evidence. UNVERIFIED means the requirement could not "
    "be tested (subjective or unsupported) and must never be treated as a pass. SpecGuard is "
    "read-only and does not detect AI authorship."
)

_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message, **extra}}


def _guard(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Turn expected exceptions into structured errors; never leak internals."""
    import functools

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except SpecificationError as exc:
            return _error(
                "invalid_specification",
                "The specification is not valid.",
                issues=[i.model_dump() for i in exc.issues],
            )
        except PathNotAllowedError as exc:
            return _error("path_not_allowed", str(exc))
        except FileAccessError as exc:
            return _error("file_error", str(exc))
        except SpecGuardError as exc:
            return _error("error", str(exc))
        except Exception as exc:
            log.exception("unexpected error in tool %s", func.__name__)
            return _error("internal_error", f"Unexpected {type(exc).__name__}; see the server log.")

    return wrapper


def create_server(roots: Sequence[Path] | None = None) -> MCPServer:
    """Build the server. `roots` are the folders file tools may read (default: current folder)."""
    allowed = [Path(r).resolve() for r in (roots or [Path.cwd()])]
    server = MCPServer("SpecGuard", instructions=INSTRUCTIONS, version=__version__)

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def extract_requirements(instructions: str) -> dict[str, Any]:
        """Turn plain-English instructions into candidate requirements.

        Only unambiguous instructions become testable rules. Everything else is returned
        with verification_type semantic, manual or unsupported. Review before using.
        """
        result = api.extract_from_text(instructions)
        spec = api.specification_from_extraction(result, "Extracted requirements")
        return {
            "ok": True,
            "specification": spec.model_dump(mode="json"),
            "interpretations": [
                {"id": i.requirement.id, "source": i.source, "interpretation": i.interpretation}
                for i in result.items
            ],
            "skipped_sentences": result.skipped,
        }

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def validate_specification(specification: dict[str, Any]) -> dict[str, Any]:
        """Check a specification (as a JSON object) without auditing anything."""
        result = api.validate_data(specification)
        return {
            "ok": result.ok,
            "valid": result.ok,
            "issues": [i.model_dump() for i in result.issues],
        }

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def audit_text(
        content: str, specification: dict[str, Any], file_type: str = "txt"
    ) -> dict[str, Any]:
        """Audit text against a specification. `file_type` is `txt` or `md`."""
        report = api.audit_text(content, specification, file_type=file_type)
        return {"ok": True, "report": report_to_dict(report)}

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def audit_file(file_path: str, specification_path: str) -> dict[str, Any]:
        """Audit a .txt, .md or .docx file against a YAML specification file.

        Both paths must be inside the folders the server was started with.
        """
        document = resolve_within(file_path, allowed)
        spec = resolve_within(specification_path, allowed)
        report = api.audit_file(document, spec)
        return {"ok": True, "report": report_to_dict(report)}

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def compare_preserved_content(
        content: str,
        protected_text: str | list[str],
        case_sensitive: bool = True,
        normalize_whitespace: bool = True,
        file_type: str = "txt",
    ) -> dict[str, Any]:
        """Check that protected passages appear in `content` exactly, with a diff if not."""
        result = api.compare_preserved(
            content,
            protected_text,
            file_type=file_type,
            case_sensitive=case_sensitive,
            normalize_whitespace=normalize_whitespace,
        )
        return {"ok": True, "result": result.model_dump(mode="json")}

    @server.tool(annotations=_READ_ONLY)
    @_guard
    def list_supported_rules() -> dict[str, Any]:
        """List every checker with a summary of its parameters."""
        return {"ok": True, "rules": api.list_rules()}

    return server
