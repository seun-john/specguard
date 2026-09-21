"""preserve_text: protected text must appear unchanged; if not, show what changed."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, ClassVar

from specguard.errors import DocumentReadError, PathNotAllowedError
from specguard.models.document import Document, TextUnit
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult, Location
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import (
    ParameterError,
    get_bool,
    get_choice,
    get_str_list,
    reject_unknown,
)
from specguard.utils.diff import sentences, word_diff
from specguard.utils.paths import (
    MAX_BASELINE_BYTES,
    decode_text,
    read_bytes_limited,
    resolve_within,
)
from specguard.utils.text import collapse_whitespace, truncate

# A near-match must contain at least this share of the protected words, in order.
NEAR_MATCH_THRESHOLD = 0.6

_QUOTE_MAP = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


@dataclass
class _Config:
    texts: list[str]
    baseline_file: str | None
    split: str
    case_sensitive: bool
    normalize_whitespace: bool
    normalize_quotes: bool


@register_rule
class PreservationRule(RuleChecker):
    rule_type = "preserve_text"
    summary = "Protected text must appear in the document exactly as given."
    parameter_help: ClassVar[dict[str, str]] = {
        "text / texts": "The protected text, inline. Each entry must appear unchanged.",
        "baseline_file": "A file holding the protected text, relative to the specification's "
        "folder (it may not point outside that folder).",
        "split": "How a baseline file is divided into protected items: `lines` (default), "
        "`paragraphs` (blank-line separated) or `whole`.",
        "case_sensitive": "Compare case exactly (default true).",
        "normalize_whitespace": "Treat any run of whitespace as one space (default true).",
        "normalize_quotes": "Treat curly and straight quotes as equal (default false).",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(
            parameters,
            (
                "text",
                "texts",
                "baseline_file",
                "split",
                "case_sensitive",
                "normalize_whitespace",
                "normalize_quotes",
            ),
        )
        inline = get_str_list(parameters, "texts", "text", required=False)
        baseline = parameters.get("baseline_file")
        if baseline is not None and not isinstance(baseline, str):
            raise ParameterError("'baseline_file' must be a path string")
        if not inline and baseline is None:
            raise ParameterError("give 'text', 'texts' or 'baseline_file'")
        return _Config(
            texts=inline,
            baseline_file=baseline,
            split=get_choice(parameters, "split", ("lines", "paragraphs", "whole"), "lines"),
            case_sensitive=get_bool(parameters, "case_sensitive", True),
            normalize_whitespace=get_bool(parameters, "normalize_whitespace", True),
            normalize_quotes=get_bool(parameters, "normalize_quotes", False),
        )

    # -- helpers -----------------------------------------------------------------------

    def _load_items(self, cfg: _Config) -> list[str]:
        items = list(cfg.texts)
        if cfg.baseline_file is not None:
            base = self.context.base_dir
            if base is None:
                raise ParameterError(
                    "'baseline_file' needs a specification file location; use inline 'text' instead"
                )
            try:
                path = resolve_within(cfg.baseline_file, [base])
                content, _ = decode_text(read_bytes_limited(path, MAX_BASELINE_BYTES), str(path))
            except PathNotAllowedError as exc:
                raise ParameterError(
                    f"baseline_file must be inside the specification's folder ({base})"
                ) from exc
            except DocumentReadError as exc:
                raise ParameterError(f"cannot read baseline_file: {exc}") from exc
            if cfg.split == "lines":
                chunks = content.split("\n")
            elif cfg.split == "paragraphs":
                chunks = re.split(r"\n\s*\n", content)
            else:
                chunks = [content]
            items.extend(c.strip() for c in chunks if c.strip())
        if not items:
            raise ParameterError("the protected text is empty")
        return items

    @staticmethod
    def _normalizer(cfg: _Config) -> Any:
        def norm(text: str) -> str:
            if cfg.normalize_quotes:
                text = text.translate(_QUOTE_MAP)
            if cfg.normalize_whitespace:
                text = collapse_whitespace(text)
            return text if cfg.case_sensitive else text.casefold()

        return norm

    def validate_parameters(self, parameters: Mapping[str, Any]) -> list[str]:
        try:
            cfg = self.parse(parameters)
            if cfg.baseline_file is not None:
                self._load_items(cfg)
        except ParameterError as exc:
            return [str(exc)]
        return []

    # -- check -------------------------------------------------------------------------

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        items = self._load_items(cfg)
        norm = self._normalizer(cfg)
        units = list(document.units())
        normalized_units = [(u, norm(u.text)) for u in units]
        whole = norm("\n\n".join(u.text for u in units))

        outcomes: list[dict[str, Any]] = []
        for item in items:
            needle = norm(item)
            location = next((u.location for u, text in normalized_units if needle in text), None)
            if location is not None or needle in whole:
                outcomes.append({"expected": item, "status": "ok", "location": location})
                continue
            outcomes.append(self._explain_change(item, needle, normalized_units, norm))

        bad = [o for o in outcomes if o["status"] != "ok"]
        expected = truncate(items[0], 300) if len(items) == 1 else f"{len(items)} protected items"
        if not bad:
            return self.passed(
                requirement,
                f"All {len(items)} protected item(s) appear unchanged.",
                expected=expected,
                actual="Found exactly as given",
                locations=[o["location"] for o in outcomes if o["location"] is not None],
                details={"items": len(items)},
            )

        modified = [o for o in bad if o["status"] == "modified"]
        evidence: list[str] = []
        for o in bad[:10]:
            evidence.append(f"Expected: {truncate(o['expected'], 300)}")
            evidence.append(
                f"Found: {truncate(o['found'], 300)}" if o["found"] else "Found: (nothing similar)"
            )
            if o["diff"]:
                evidence.append(f"Changes: {o['diff']}")
        if len(bad) > 10:
            evidence.append(f"... and {len(bad) - 10} more changed or missing items")
        first = bad[0]
        message = (
            "Protected text was modified."
            if len(modified) == len(bad)
            else "Protected text was modified or missing."
        )
        return self.failed(
            requirement,
            f"{message} {len(bad)} of {len(items)} item(s) do not appear exactly as given.",
            expected=truncate(first["expected"], 300),
            actual=truncate(first["found"], 300) if first["found"] else "(not found)",
            evidence=evidence,
            locations=[o["location"] for o in bad if o["location"] is not None],
            remediation_hint="Restore the protected wording exactly; do not rephrase it.",
            details={
                "items": len(items),
                "changed": len(modified),
                "missing": len(bad) - len(modified),
            },
        )

    @staticmethod
    def _explain_change(
        item: str, needle: str, units: list[tuple[TextUnit, str]], norm: Any
    ) -> dict[str, Any]:
        """Find the closest passage to a protected item and describe how it differs."""
        needle_words = needle.split()
        wanted = set(needle_words)
        best: tuple[float, TextUnit | None, str] = (0.0, None, "")
        for unit, text in units:
            words = text.split()
            if not wanted or len(wanted & set(words)) / len(wanted) < 0.5:
                continue
            # Compare against the whole unit and each sentence in it; keep the best window.
            # Word lists are aligned, so the original (un-normalized) words can be quoted back.
            candidates = [(unit.text, text)] + [(s, norm(s)) for _, s in sentences(unit.text)]
            for original, normalized in candidates:
                cand_words = normalized.split()
                orig_words = collapse_whitespace(original).split()
                sm = SequenceMatcher(None, needle_words, cand_words, autojunk=False)
                blocks = [b for b in sm.get_matching_blocks() if b.size]
                if not blocks:
                    continue
                coverage = sum(b.size for b in blocks) / len(needle_words)
                if coverage > best[0]:
                    lo = blocks[0].b
                    hi = blocks[-1].b + blocks[-1].size
                    best = (coverage, unit, " ".join(orig_words[lo:hi]))
        score, best_unit, found = best
        if best_unit is None or score < NEAR_MATCH_THRESHOLD:
            return {
                "expected": item,
                "status": "missing",
                "found": "",
                "diff": "",
                "location": None,
            }
        loc: Location = best_unit.location.model_copy()
        loc.excerpt = truncate(found, 120)
        return {
            "expected": item,
            "status": "modified",
            "found": found,
            "diff": word_diff(collapse_whitespace(item), found),
            "location": loc,
        }
