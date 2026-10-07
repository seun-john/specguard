"""Done-check: does the folder back up a claim that the work is finished?

It tests what a folder can prove (files exist and are non-empty, hashes match, JSON parses,
no placeholder markers, every acceptance criterion points at evidence) and refuses to call
the work complete without a test record that matches the current files.

A test record is produced by `capture_command`, which runs the command itself instead of
trusting a claim that it was run. The record is tamper-evident (a content hash), not
tamper-proof: anyone with write access can forge both the record and its hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from specguard.errors import FileAccessError, PathNotAllowedError, SpecGuardError
from specguard.models.result import CheckResult, Status
from specguard.project.report import ProjectReport
from specguard.utils.paths import decode_text, resolve_within

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}
TAIL_CHARS = 4000
PLACEHOLDER = re.compile(
    r"\b(TODO|FIXME|NotImplementedError)\b|@(?:pytest\.)?mark\.skip|@unittest\.skip"
)
RECORD_SCHEMA = 1


# -- snapshot -----------------------------------------------------------------------------


def _files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        yield path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root: Path, exclude: Sequence[Path] = ()) -> str:
    """One hash of every file in `root` (relative path + content), skipping build noise and
    anything in `exclude`. Any change to any file changes the snapshot."""
    root = root.resolve()
    skip = {p.resolve() for p in exclude}
    table = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in _files(root)
        if path.resolve() not in skip
    }
    return hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest()


# -- capturing a test run ------------------------------------------------------------------


def parse_test_counts(output: str) -> dict[str, int]:
    """Read pytest or unittest summary lines. Returns only the counts it can see."""
    counts: dict[str, int] = {}
    for label, key in (
        ("passed", "passed"),
        ("failed", "failed"),
        ("skipped", "skipped"),
        ("error", "errors"),
        ("errors", "errors"),
    ):
        match = re.search(rf"(\d+) {label}\b", output)
        if match:
            counts[key] = max(counts.get(key, 0), int(match.group(1)))
    if not counts:
        ran = re.search(r"^Ran (\d+) tests?", output, re.M)
        if ran:
            total = int(ran.group(1))
            failures = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", output))
            skipped = re.search(r"skipped=(\d+)", output)
            skip = int(skipped.group(1)) if skipped else 0
            counts = {"passed": max(total - failures - skip, 0), "failed": failures}
            if skip:
                counts["skipped"] = skip
    return counts


def _record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def capture_command(
    command: Sequence[str],
    root: Path,
    output: Path,
    *,
    timeout: float = 600.0,
) -> dict[str, Any]:
    """Run `command` in `root` (no shell) and write a test record to `output`."""
    if not command:
        raise SpecGuardError("No command given to run.")
    root = root.resolve()
    output = output.resolve()
    before = snapshot(root, [output])
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = -1
        stdout = (
            exc.stdout.decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
    except FileNotFoundError as exc:
        raise FileAccessError(f"Cannot run {command[0]!r}: {exc.strerror or exc}") from exc
    duration = round(time.monotonic() - clock, 3)
    after = snapshot(root, [output])
    record: dict[str, Any] = {
        "schema_version": RECORD_SCHEMA,
        "captured_by": "specguard done record",
        "command": list(command),
        "started_at": started.isoformat(timespec="seconds"),
        "duration_seconds": duration,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "snapshot": after,
        "snapshot_before_run": before,
        "files_changed_during_run": before != after,
        "counts": parse_test_counts(stdout + "\n" + stderr),
        "stdout_tail": stdout[-TAIL_CHARS:],
        "stderr_tail": stderr[-TAIL_CHARS:],
    }
    record["record_hash"] = _record_hash(record)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


# -- the audit -----------------------------------------------------------------------------


class _Builder:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, status: Status, message: str, **kw: Any) -> None:
        self.results.append(
            CheckResult(
                requirement_id=f"DP{len(self.results) + 1:03d}",
                status=status,
                message=message,
                checker="done",
                **kw,
            )
        )


def _need_list(spec: dict[str, Any], key: str) -> list[Any]:
    value = spec.get(key, [])
    if not isinstance(value, list):
        raise SpecGuardError(f"'{key}' must be a list")
    return value


def audit_done(spec: dict[str, Any], root: Path) -> ProjectReport:
    """Audit `root` against a done-spec (already parsed from YAML or JSON)."""
    root = root.resolve()
    if not root.is_dir():
        raise FileAccessError(f"Project root is not a directory: {root}")
    unknown = set(spec) - {"files", "scan_files", "criteria", "test_record"}
    if unknown:
        raise SpecGuardError("Unknown done-spec key(s): " + ", ".join(sorted(unknown)))
    out = _Builder()

    def inside(rel: Any) -> Path:
        if not isinstance(rel, str) or not rel:
            raise SpecGuardError("Paths in a done-spec must be non-empty strings")
        try:
            return resolve_within(rel, [root])
        except PathNotAllowedError as exc:
            raise SpecGuardError(str(exc)) from exc

    for item in _need_list(spec, "files"):
        rel = item.get("path") if isinstance(item, dict) else None
        path = inside(rel)
        evidence = [f"path: {rel}"]
        if not path.is_file():
            out.add(Status.FAIL, f"Expected file is missing: {rel}", evidence=evidence)
            continue
        if path.stat().st_size == 0:
            out.add(Status.FAIL, f"File exists but is empty: {rel}", evidence=evidence)
            continue
        problems = []
        wanted = item.get("sha256")
        if wanted and _sha256(path) != str(wanted).lower():
            problems.append("sha256 differs from the expected hash")
        if item.get("format") == "json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                problems.append("not valid JSON")
        if problems:
            out.add(Status.FAIL, f"{rel}: " + "; ".join(problems), evidence=evidence)
        else:
            out.add(Status.PASS, f"File present and checks passed: {rel}", evidence=evidence)

    for rel in _need_list(spec, "scan_files"):
        path = inside(rel)
        if not path.is_file():
            out.add(Status.FAIL, f"File to scan is missing: {rel}")
            continue
        try:
            text, _ = decode_text(path.read_bytes(), str(rel))
        except (FileAccessError, OSError) as exc:
            out.add(Status.UNVERIFIED, f"Could not scan {rel}: {exc}")
            continue
        hits = [
            f"line {n}: {line.strip()[:120]}"
            for n, line in enumerate(text.splitlines(), 1)
            if PLACEHOLDER.search(line)
        ]
        if hits:
            out.add(
                Status.WARNING,
                f"{rel} contains {len(hits)} placeholder or skipped-test marker(s).",
                evidence=hits[:20],
                remediation_hint="Finish or remove the marker, or confirm it is intentional.",
            )
        else:
            out.add(Status.PASS, f"No placeholder markers in {rel}.")

    for criterion in _need_list(spec, "criteria"):
        if not isinstance(criterion, dict) or not criterion.get("text"):
            raise SpecGuardError("Each criterion needs a 'text'")
        files = criterion.get("evidence_files", [])
        if not isinstance(files, list):
            raise SpecGuardError("'evidence_files' must be a list")
        missing = [f for f in files if not inside(f).is_file()]
        text = str(criterion["text"])
        if not files:
            out.add(Status.FAIL, f"No evidence listed for criterion: {text}")
        elif missing:
            out.add(
                Status.FAIL,
                f"Evidence file(s) missing for criterion: {text}",
                evidence=[f"missing: {m}" for m in missing],
            )
        else:
            out.add(
                Status.UNVERIFIED,
                f"Evidence exists, but only a person can judge whether it satisfies: {text}",
                evidence=[f"evidence: {f}" for f in files],
            )

    _check_test_record(spec, root, inside, out)
    return ProjectReport(
        kind="done",
        root=str(root),
        results=out.results,
        notices=[
            "A done-check can show that work is not done. It cannot show that it is: "
            "acceptance criteria and test quality still need a human."
        ],
    )


def _check_test_record(spec: dict[str, Any], root: Path, inside: Any, out: _Builder) -> None:
    rel = spec.get("test_record")
    if not rel:
        out.add(
            Status.UNVERIFIED,
            "No test record supplied, so passing tests are not evidenced.",
            remediation_hint="Run: specguard done record -- <your test command>",
        )
        return
    path = inside(rel)
    if not path.is_file():
        out.add(Status.FAIL, f"Test record not found: {rel}")
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        out.add(Status.FAIL, f"Test record is not valid JSON: {rel}")
        return
    if not isinstance(record, dict) or record.get("schema_version") != RECORD_SCHEMA:
        out.add(Status.FAIL, "Test record has an unknown format.")
        return
    problems: list[str] = []
    if record.get("record_hash") != _record_hash(record):
        problems.append("record was edited after capture (hash mismatch)")
    current = snapshot(root, [path])
    if record.get("snapshot") != current:
        problems.append("files changed since the tests ran (stale record)")
    if record.get("exit_code") != 0:
        problems.append(f"command exited with {record.get('exit_code')}")
    if record.get("timed_out"):
        problems.append("command timed out")
    if record.get("files_changed_during_run"):
        problems.append("files changed while the tests were running")
    counts = record.get("counts") or {}
    passed = counts.get("passed", 0)
    bad = counts.get("failed", 0) + counts.get("errors", 0)
    if bad:
        problems.append(f"{bad} test(s) failed or errored")
    if not counts:
        problems.append("no test counts could be read from the output")
    elif passed < 1:
        problems.append("no passing tests were reported")
    command = " ".join(record.get("command", []))
    evidence = [f"command: {command}", f"counts: {counts}", f"current snapshot: {current[:16]}"]
    if problems:
        out.add(
            Status.FAIL, "Test record does not support completion.", evidence=problems + evidence
        )
    elif counts.get("skipped"):
        out.add(
            Status.WARNING,
            f"Tests passed but {counts['skipped']} were skipped.",
            evidence=evidence,
        )
    else:
        out.add(
            Status.PASS,
            "Captured test run matches the current files.",
            evidence=evidence,
            confidence=0.8,
            details={"note": "Tamper-evident, not tamper-proof."},
        )
