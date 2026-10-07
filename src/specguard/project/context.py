"""Context lint: are the instruction files an AI agent will read consistent and safe?

Looks for AGENTS.md, CLAUDE.md, GEMINI.md, .cursorrules and Copilot instruction files,
then reports duplicates, direct contradictions, bloat, broken `@file` imports and lines
that tell an agent to disclose credentials. It matches literal wording; it does not
understand meaning, so a missing conflict is not proof that none exists.
"""

from __future__ import annotations

import re
from pathlib import Path

from specguard.errors import FileAccessError
from specguard.models.result import CheckResult, Location, Status
from specguard.project.done import EXCLUDED_DIRS
from specguard.project.report import ProjectReport
from specguard.utils.paths import decode_text, is_within

INSTRUCTION_NAMES = {
    "agents.md",
    "claude.md",
    "gemini.md",
    ".cursorrules",
    "copilot-instructions.md",
}
BLOAT_CHARS = 16_000
POSITIVE = re.compile(r"^(?:always|you must|must)\s+(.+)$")
NEGATIVE = re.compile(r"^(?:never|do not|don't|dont|you must not|must not)\s+(.+)$")
DISCLOSE = re.compile(
    r"\b(send|upload|post|reveal|print|echo|expose|share)\b.*"
    r"\b(password|credentials?|secret|api[ _-]?key|token|private key)\b",
    re.I,
)
IMPORT = re.compile(r"(?<![\w@])@([\w./\\-]+\.\w+)")
NEGATED_DISCLOSURE = re.compile(r"\b(never|do not|don't|must not|avoid)\b", re.I)


def _instruction_files(root: Path) -> list[Path]:
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in rel.parts) or path.is_symlink():
            continue
        if path.is_file() and path.name.lower() in INSTRUCTION_NAMES:
            found.append(path)
    return found


def _normal(line: str) -> str:
    line = re.sub(r"^[\s>*\-+\d.)]+", "", line).strip().lower()
    return re.sub(r"[\s`*_]+", " ", line).rstrip(".!")


def audit_context(root: Path, target: str = ".") -> ProjectReport:
    """Lint every instruction file under `root` that applies to `target`."""
    root = root.resolve()
    if not root.is_dir():
        raise FileAccessError(f"Project root is not a directory: {root}")
    goal = (root / target).resolve()
    if not is_within(goal, root):
        raise FileAccessError(f"Target is outside the project root: {target}")
    results: list[CheckResult] = []

    def add(status: Status, message: str, **kw: object) -> None:
        results.append(
            CheckResult(
                requirement_id=f"CL{len(results) + 1:03d}",
                status=status,
                message=message,
                checker="context",
                **kw,
            )
        )

    files = _instruction_files(root)
    seen: dict[str, tuple[str, int]] = {}
    positive: dict[str, tuple[str, int]] = {}
    negative: dict[str, tuple[str, int]] = {}
    summary = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        applies = path.parent == goal or path.parent in goal.parents
        try:
            text, _ = decode_text(path.read_bytes(), rel)
        except (FileAccessError, OSError) as exc:
            add(Status.UNVERIFIED, f"Could not read {rel}: {exc}")
            continue
        summary.append(
            {
                "path": rel,
                "applies_to_target": applies,
                "characters": len(text),
                "estimated_tokens": (len(text) + 3) // 4,
            }
        )
        if len(text) > BLOAT_CHARS:
            add(
                Status.WARNING,
                f"{rel} is {len(text):,} characters; long instruction files get skimmed.",
                remediation_hint="Move rarely needed detail into linked documents.",
            )
        in_code = False
        for number, raw in enumerate(text.splitlines(), 1):
            if raw.strip().startswith("```"):
                in_code = not in_code
                continue
            line = _normal(raw)
            if in_code or not line or raw.lstrip().startswith("#"):
                continue
            where = Location(line=number, excerpt=raw.strip()[:120])
            for name in IMPORT.findall(raw):
                if not (path.parent / name).exists() and not (root / name).exists():
                    add(
                        Status.FAIL,
                        f"{rel}:{number} imports @{name}, which does not exist.",
                        locations=[where],
                    )
            if DISCLOSE.search(line) and not NEGATED_DISCLOSURE.search(line):
                add(
                    Status.FAIL,
                    f"{rel}:{number} appears to tell the agent to disclose a credential.",
                    locations=[where],
                    evidence=[raw.strip()[:200]],
                )
            if not applies:
                continue
            if line in seen:
                first = seen[line]
                add(
                    Status.WARNING,
                    f"Duplicate instruction at {rel}:{number} (first at {first[0]}:{first[1]}).",
                    locations=[where],
                )
            else:
                seen[line] = (rel, number)
            for table, pattern, opposite in (
                (positive, POSITIVE, negative),
                (negative, NEGATIVE, positive),
            ):
                match = pattern.match(line)
                if not match:
                    continue
                action = match.group(1)
                if action in opposite:
                    other = opposite[action]
                    add(
                        Status.FAIL,
                        f"Contradiction on '{action}': {rel}:{number} versus "
                        f"{other[0]}:{other[1]}.",
                        locations=[where],
                        remediation_hint="Keep one rule, or say when each applies.",
                    )
                table.setdefault(action, (rel, number))
    if not files:
        add(Status.UNVERIFIED, "No instruction files (AGENTS.md, CLAUDE.md, ...) were found.")
    return ProjectReport(
        kind="context",
        root=str(root),
        results=results,
        data={"instruction_files": summary},
        notices=[
            "Matches literal wording and folder ancestry only. It does not model "
            "editor-specific precedence or paraphrased contradictions."
        ],
    )
