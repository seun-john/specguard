"""Command-line interface. Thin: every command calls the shared core in `specguard.api`."""

from __future__ import annotations

import contextlib
import functools
import os
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from specguard import __version__, api
from specguard.audit.policy import blocking_entries
from specguard.errors import FileAccessError, SpecGuardError
from specguard.models.specification import SpecificationError, ValidationIssue
from specguard.reports import FORMATS, render_report, render_terminal
from specguard.spec_yaml import INIT_TEMPLATE, dump_specification
from specguard.utils.paths import MAX_DOCUMENT_BYTES, decode_text, read_bytes_limited

# Exit codes are part of the public interface; see the README.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BAD_SPEC = 2
EXIT_FILE_ERROR = 3
EXIT_INTERNAL = 4

DEFAULT_SPEC = "specguard.yml"

app = typer.Typer(
    name="specguard",
    help="Verify that AI-generated work actually follows the instructions.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

err = Console(stderr=True)

F = TypeVar("F", bound=Callable[..., Any])


class OutputFormat(str, Enum):
    terminal = "terminal"
    json = "json"
    markdown = "markdown"
    sarif = "sarif"


class FailOn(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"
    any = "any"
    none = "none"


def _print_issues(issues: list[ValidationIssue]) -> None:
    for issue in issues:
        style = "red" if issue.level == "error" else "yellow"
        err.print(f"  [{style}]{issue.level}[/{style}] {_escape(str(issue))}")


def _escape(text: str) -> str:
    return escape(text)


def handle_errors(func: F) -> F:
    """Map expected exceptions to documented exit codes; never show a traceback by default."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except SpecificationError as exc:
            err.print("[red]Invalid specification[/red]")
            _print_issues(exc.issues)
            raise typer.Exit(EXIT_BAD_SPEC) from None
        except FileAccessError as exc:
            err.print(f"[red]File error:[/red] {_escape(str(exc))}")
            raise typer.Exit(EXIT_FILE_ERROR) from None
        except SpecGuardError as exc:
            err.print(f"[red]Error:[/red] {_escape(str(exc))}")
            raise typer.Exit(EXIT_FILE_ERROR) from None
        except Exception as exc:
            if os.environ.get("SPECGUARD_DEBUG"):
                raise
            err.print(
                f"[red]Internal error:[/red] {type(exc).__name__}. "
                "Set SPECGUARD_DEBUG=1 for a traceback, and please report it."
            )
            raise typer.Exit(EXIT_INTERNAL) from None

    return wrapper  # type: ignore[return-value]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"specguard {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """SpecGuard checks whether an output followed the brief. It tests the document; it does
    not trust anyone's claim that the instructions were followed."""


def _refuse_overwrite(path: Path, force: bool) -> None:
    if path.exists() and not force:
        err.print(
            f"[red]File error:[/red] {_escape(str(path))} already exists. "
            "Use --force to overwrite it."
        )
        raise typer.Exit(EXIT_FILE_ERROR)


def _write_text(path: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise FileAccessError(f"Cannot write {path}: {exc.strerror or exc}") from exc


# --------------------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------------------


@app.command()
@handle_errors
def init(
    path: Path = typer.Argument(
        Path(DEFAULT_SPEC), help="Where to write the starter specification."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite the file if it exists."),
) -> None:
    """Create a commented starter specification."""
    _refuse_overwrite(path, force)
    _write_text(path, INIT_TEMPLATE)
    typer.echo(f"Created {path}")
    typer.echo(f"Next: edit it, then run:  specguard audit <your-file> --spec {path}")


# --------------------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------------------


@app.command()
@handle_errors
def extract(
    instructions: Path = typer.Argument(
        ..., help="Text or Markdown file containing the instructions."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the specification here."
    ),
    name: str | None = typer.Option(None, "--name", help="Name for the specification."),
    explain: bool = typer.Option(
        False, "--explain", help="Show how each sentence was interpreted."
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite the output file if it exists."),
) -> None:
    """Turn natural-language instructions into a specification (candidate requirements).

    Only unambiguous instructions become tests. Everything else is kept and marked
    semantic, manual or unsupported, so it is reported UNVERIFIED. Review the result.
    """
    if output is not None:
        _refuse_overwrite(output, force)
    text, _ = decode_text(read_bytes_limited(instructions, MAX_DOCUMENT_BYTES), str(instructions))
    result = api.extract_from_text(text)
    spec = api.specification_from_extraction(
        result, name or f"Requirements from {instructions.name}"
    )
    checked = sum(1 for r in spec.requirements if r.is_deterministic)
    header = (
        f"Generated by `specguard extract` from {instructions.name}.\n"
        "Review every requirement. Rules marked semantic, manual or unsupported are reported\n"
        "UNVERIFIED; SpecGuard does not guess a test for them."
    )
    yaml_text = dump_specification(spec, header)

    if explain:
        table = Table(title="How each requirement was read", show_lines=True)
        for col in ("Id", "Instruction", "Interpretation", "Type", "Checker"):
            table.add_column(col, overflow="fold")
        for item in result.items:
            r = item.requirement
            table.add_row(
                r.id,
                item.source,
                item.interpretation,
                (r.verification_type.value if r.verification_type else ""),
                r.checker or "-",
            )
        err.print(table)
        if result.skipped:
            err.print("[dim]Skipped (not instructions):[/dim]")
            for s in result.skipped:
                err.print(f"  [dim]- {_escape(s)}[/dim]")
    err.print(
        f"Found {len(spec.requirements)} requirement(s): {checked} testable, "
        f"{len(spec.requirements) - checked} that SpecGuard cannot test (they will be UNVERIFIED)."
    )
    if not spec.requirements:
        err.print(
            "[yellow]No requirements were recognised. Write one instruction per sentence.[/yellow]"
        )

    if output is not None:
        _write_text(output, yaml_text)
        err.print(f"Wrote {output}")
    else:
        typer.echo(yaml_text, nl=False)


# --------------------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------------------


@app.command()
@handle_errors
def validate(
    specification: Path = typer.Argument(Path(DEFAULT_SPEC), help="Specification file to check."),
) -> None:
    """Check a specification for mistakes without auditing anything."""
    result = api.validate_file(specification)
    if result.warnings:
        err.print("[yellow]Warnings[/yellow]")
        _print_issues(result.warnings)
    if not result.ok or result.spec is None:
        err.print(f"[red]{specification} is not valid[/red] ({len(result.errors)} error(s))")
        _print_issues(result.errors)
        raise typer.Exit(EXIT_BAD_SPEC)
    spec = result.spec
    testable = sum(1 for r in spec.enabled_requirements() if r.is_deterministic)
    total = len(spec.enabled_requirements())
    typer.echo(
        f"{specification} is valid: {total} requirement(s), {testable} testable, "
        f"{total - testable} not testable."
    )


# --------------------------------------------------------------------------------------
# audit
# --------------------------------------------------------------------------------------


@app.command()
@handle_errors
def audit(
    file: Path = typer.Argument(
        ..., help="Document to audit (.txt, .md or .docx). It is never modified."
    ),
    spec: Path = typer.Option(Path(DEFAULT_SPEC), "--spec", "-s", help="Specification file."),
    format: OutputFormat = typer.Option(
        OutputFormat.terminal, "--format", "-f", help="Report format."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the report to this file."
    ),
    fail_on: FailOn = typer.Option(
        FailOn.any,
        "--fail-on",
        help="Exit with 1 when a failure at this severity or worse is found. "
        "'any' means any FAIL or ERROR.",
    ),
    fail_on_unverified: bool = typer.Option(
        False, "--fail-on-unverified", help="Also exit with 1 if any requirement was not tested."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show evidence for passing requirements too."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colour."),
) -> None:
    """Audit a document against a specification and report the evidence."""
    if output is not None and output.resolve() in {file.resolve(), spec.resolve()}:
        raise SpecGuardError(f"Refusing to write the report over an input file: {output}")
    if not spec.exists() and str(spec) == DEFAULT_SPEC:
        raise FileAccessError(
            f"No {DEFAULT_SPEC} in this folder. Create one with `specguard init`, or pass --spec."
        )

    report = api.audit_file(file, spec)
    fmt = format.value
    assert fmt in FORMATS

    if output is not None:
        _write_text(output, render_report(report, fmt, verbose=verbose))
        c = report.summary.counts
        err.print(
            f"Wrote {fmt} report to {output} "
            f"({c['PASS']} passed, {c['FAIL']} failed, {c['UNVERIFIED']} unverified)"
        )
    elif fmt == "terminal":
        render_terminal(report, Console(no_color=no_color), verbose=verbose)
    else:
        typer.echo(render_report(report, fmt), nl=False)

    if blocking_entries(report, fail_on.value, fail_on_unverified=fail_on_unverified):
        raise typer.Exit(EXIT_FAILED)


# --------------------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------------------


@app.command()
@handle_errors
def rules(
    name: str | None = typer.Argument(None, help="Show the parameters of one checker."),
) -> None:
    """List the available checkers."""
    described = api.list_rules()
    if name:
        match = next((r for r in described if r["rule_type"] == name), None)
        if match is None:
            raise SpecGuardError(f"Unknown checker '{name}'. Run `specguard rules` to list them.")
        typer.echo(f"{match['rule_type']}: {match['summary']}\n")
        for param, help_text in match["parameters"].items():
            typer.echo(f"  {param}\n      {help_text}")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Checker")
    table.add_column("What it checks", overflow="fold")
    for r in described:
        table.add_row(r["rule_type"], r["summary"])
    Console().print(table)
    typer.echo("Run `specguard rules <name>` for a checker's parameters.")


# --------------------------------------------------------------------------------------
# mcp
# --------------------------------------------------------------------------------------


class Transport(str, Enum):
    stdio = "stdio"
    streamable_http = "streamable-http"


@app.command()
@handle_errors
def mcp(
    transport: Transport = typer.Option(
        Transport.stdio, "--transport", "-t", help="How clients connect."
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address for streamable-http."),
    port: int = typer.Option(8000, "--port", help="Port for streamable-http."),
    root: list[Path] | None = typer.Option(
        None,
        "--root",
        help="Folder the server may read files from. Repeatable. Default: the current folder.",
    ),
) -> None:
    """Run the SpecGuard MCP server (stdio by default)."""
    from specguard.mcp.server import create_server

    roots = [r.resolve() for r in root] if root else [Path.cwd().resolve()]
    server = create_server(roots)
    if transport is Transport.stdio:
        server.run("stdio")
    else:
        err.print(
            f"SpecGuard MCP on http://{host}:{port}/mcp "
            f"(reads files under: {', '.join(map(str, roots))})"
        )
        server.run("streamable-http", host=host, port=port)


# --------------------------------------------------------------------------------------
# project-level audits: done, context, scope
# --------------------------------------------------------------------------------------

done_app = typer.Typer(help="Check whether a folder backs up a 'done' claim.", no_args_is_help=True)
scope_app = typer.Typer(
    help="Check which files changed, and whether that was allowed.", no_args_is_help=True
)
app.add_typer(done_app, name="done")
app.add_typer(scope_app, name="scope")


class ProjectFormat(str, Enum):
    terminal = "terminal"
    json = "json"
    markdown = "markdown"


def _emit_project(
    report: Any, fmt: ProjectFormat, output: Path | None, fail_on_unverified: bool
) -> None:
    from specguard.project import render_project_report

    text = render_project_report(report, fmt.value)
    if output is not None:
        _write_text(output, text)
        err.print(f"Wrote {fmt.value} report to {output}")
    else:
        typer.echo(text, nl=False)
    if report.failed() or (fail_on_unverified and report.has_unverified()):
        raise typer.Exit(EXIT_FAILED)


def _load_mapping(path: Path) -> dict[str, Any]:
    from specguard.utils.yamlio import YamlLoadError, load_yaml_text

    text, _ = decode_text(read_bytes_limited(path, 1024 * 1024), str(path))
    try:
        data = load_yaml_text(text)  # YAML is a superset of JSON, so both work
    except YamlLoadError as exc:
        raise SpecGuardError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecGuardError(f"{path} must contain a mapping at the top level")
    return data


@done_app.command("check")
@handle_errors
def done_check(
    spec: Path = typer.Argument(
        ..., help="Done-spec (YAML or JSON): files, scan_files, criteria, test_record."
    ),
    root: Path = typer.Option(
        Path("."), "--root", help="Project folder the paths are relative to."
    ),
    format: ProjectFormat = typer.Option(ProjectFormat.terminal, "--format", "-f"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    fail_on_unverified: bool = typer.Option(False, "--fail-on-unverified"),
) -> None:
    """Audit a folder against a done-spec. Exit 1 on any failure."""
    from specguard.project import audit_done

    _emit_project(audit_done(_load_mapping(spec), root), format, output, fail_on_unverified)


@done_app.command(
    "record", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
@handle_errors
def done_record(
    ctx: typer.Context,
    output: Path = typer.Option(
        Path("test-record.json"), "--output", "-o", help="Where to write the record."
    ),
    root: Path = typer.Option(Path("."), "--root"),
    timeout: float = typer.Option(
        600.0, "--timeout", help="Seconds before the command is stopped."
    ),
) -> None:
    """Run a test command (after `--`) and write a tamper-evident record of what happened.

    Example: specguard done record -o test-record.json -- python -m pytest -q
    """
    from specguard.project import capture_command

    record = capture_command(ctx.args, root, output, timeout=timeout)
    typer.echo(f"Recorded exit code {record['exit_code']}, counts {record['counts']} -> {output}")
    if record["exit_code"] != 0:
        raise typer.Exit(EXIT_FAILED)


@app.command()
@handle_errors
def context(
    root: Path = typer.Option(Path("."), "--root", help="Project folder to scan."),
    target: str = typer.Option(
        ".", "--target", help="Folder (inside root) the agent will work in."
    ),
    format: ProjectFormat = typer.Option(ProjectFormat.terminal, "--format", "-f"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    fail_on_unverified: bool = typer.Option(False, "--fail-on-unverified"),
) -> None:
    """Lint AGENTS.md, CLAUDE.md and similar instruction files for conflicts and risks."""
    from specguard.project import audit_context

    _emit_project(audit_context(root, target), format, output, fail_on_unverified)


@scope_app.command("snapshot")
@handle_errors
def scope_snapshot(
    root: Path = typer.Option(Path("."), "--root"),
    output: Path = typer.Option(
        ..., "--output", "-o", help="Save the baseline outside the folder."
    ),
) -> None:
    """Record file hashes before the work starts."""
    import json

    from specguard.project import manifest

    data = manifest(root)
    if output.resolve().is_relative_to(root.resolve()):
        err.print("[yellow]Warning:[/yellow] the baseline is inside the audited folder.")
    _write_text(output, json.dumps(data, indent=2, sort_keys=True) + "\n")
    typer.echo(f"Recorded {len(data)} file(s) -> {output}")


@scope_app.command("check")
@handle_errors
def scope_check(
    baseline: Path = typer.Argument(..., help="Baseline from `specguard scope snapshot`."),
    allow: list[str] = typer.Option(
        ..., "--allow", help="Path pattern that may change. Repeatable."
    ),
    protect: list[str] = typer.Option([], "--protect", help="Path pattern that must not change."),
    root: Path = typer.Option(Path("."), "--root"),
    format: ProjectFormat = typer.Option(ProjectFormat.terminal, "--format", "-f"),
    output: Path | None = typer.Option(None, "--output", "-o"),
) -> None:
    """Compare the folder with a baseline and flag out-of-scope or protected changes."""
    from specguard.project import audit_scope, load_baseline

    report = audit_scope(root, load_baseline(baseline), allow, protect)
    _emit_project(report, format, output, False)


def main() -> None:
    """Console-script entry point."""
    for stream in (sys.stdout, sys.stderr):
        # Windows consoles default to a legacy code page that cannot print "—" or box lines.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(OSError, ValueError):  # exotic streams may refuse
                reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
