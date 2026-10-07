"""Scope fence: which files did a piece of work actually touch, and was that allowed?

`snapshot` records a manifest of file hashes before the work starts. `check` compares the
folder with that manifest and classifies every change against allowed and protected path
patterns. The manifest is not authenticated: whoever can edit it can hide changes.
"""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from specguard.errors import FileAccessError, SpecGuardError
from specguard.models.result import CheckResult, Status
from specguard.project.done import _files, _sha256
from specguard.project.report import ProjectReport

DEPENDENCY_FILES = {
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
}


def manifest(root: Path) -> dict[str, str]:
    """Relative path -> sha256 for every tracked file under `root`."""
    root = root.resolve()
    if not root.is_dir():
        raise FileAccessError(f"Project root is not a directory: {root}")
    return {p.relative_to(root).as_posix(): _sha256(p) for p in _files(root)}


def _matches(path: str, patterns: list[str]) -> bool:
    """Glob match (fnmatch: `*` also crosses `/`). A pattern ending in `/` covers a folder."""
    for pattern in patterns:
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return True
        elif fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _check_patterns(patterns: object, label: str) -> list[str]:
    if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
        raise SpecGuardError(f"{label} must be a list of non-empty strings")
    for p in patterns:
        parts = p.replace("\\", "/").split("/")
        if p.startswith(("/", "\\")) or ".." in parts:
            raise SpecGuardError(f"{label}: patterns must be relative with no '..': {p}")
    return [p.replace("\\", "/") for p in patterns]


def _as_list(value: object) -> object:
    return list(value) if isinstance(value, (tuple, list)) else value


def audit_scope(
    root: Path,
    baseline: dict[str, str],
    allowed: Sequence[str],
    protected: Sequence[str] = (),
) -> ProjectReport:
    allow = _check_patterns(list(allowed), "allowed")
    deny = _check_patterns(list(protected), "protected")
    for rel, digest in baseline.items():
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or set(digest) - set("0123456789abcdef")
        ):
            raise SpecGuardError(f"Baseline entry for {rel} is not a lowercase sha256 hex digest")
    current = manifest(root)
    results: list[CheckResult] = []
    for rel in sorted(set(current) | set(baseline)):
        if current.get(rel) == baseline.get(rel):
            continue
        kind = "added" if rel not in baseline else "deleted" if rel not in current else "modified"
        if _matches(rel, deny):
            status, label = Status.FAIL, "protected path changed"
        elif _matches(rel, allow):
            status, label = Status.PASS, "change is within the allowed scope"
        else:
            status, label = Status.FAIL, "change is outside the allowed scope"
        results.append(
            CheckResult(
                requirement_id=f"SC{len(results) + 1:03d}",
                status=status,
                message=f"{rel} was {kind}: {label}.",
                checker="scope",
            )
        )
        if PurePosixPath(rel).name.lower() in DEPENDENCY_FILES:
            results.append(
                CheckResult(
                    requirement_id=f"SC{len(results) + 1:03d}",
                    status=Status.WARNING,
                    message=f"{rel} is a dependency file; review install and compatibility.",
                    checker="scope",
                )
            )
    if not results:
        results.append(
            CheckResult(
                requirement_id="SC001",
                status=Status.PASS,
                message="No differences from the baseline.",
                checker="scope",
            )
        )
    return ProjectReport(
        kind="scope",
        root=str(root.resolve()),
        results=results,
        notices=[
            "Permission to change a path does not mean every change inside it was relevant. "
            "The baseline is not authenticated."
        ],
    )


def load_baseline(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FileAccessError(f"Cannot read baseline {path}: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("manifest"), dict):
        data = data["manifest"]
    if not isinstance(data, dict):
        raise SpecGuardError("Baseline must be a JSON object mapping paths to sha256 digests")
    return data
