"""Turn plain-English instructions into candidate requirements.

Design rule: accuracy over coverage. A sentence becomes a deterministic rule only when
a pattern recognises it unambiguously. Anything else that reads like an instruction is
kept, but marked `semantic`, `manual` or `unsupported`, so it is reported UNVERIFIED and
never as a pass. Sentences that are not instructions are skipped.

The extractor is a cascade of small matchers, tried in order; the first that recognises
a clause wins. It uses no model and no network access.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from specguard.models.requirement import Category, Requirement, Severity, VerificationType

D = VerificationType
I = re.IGNORECASE  # noqa: E741

# --------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------

_NUMWORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
}
_NUMWORD_RE = "|".join(sorted(_NUMWORDS, key=len, reverse=True))
NUM = rf"(?:\d[\d,]*|{_NUMWORD_RE})"
DIGITS = r"\d[\d,]*"


def to_int(token: str) -> int:
    """`1,500` -> 1500; `five` -> 5."""
    token = token.strip().lower()
    if token in _NUMWORDS:
        return _NUMWORDS[token]
    return int(token.replace(",", ""))


# --------------------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------------------

_QUOTE_RE = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<![\w])\'([^\'\n]+)\'(?![\w])')


def _quoted(text: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None).strip() for m in _QUOTE_RE.finditer(text)]


def _mask_quotes(text: str) -> str:
    """Blank out quoted spans (same length) so sentence splitting ignores their punctuation."""
    return _QUOTE_RE.sub(
        lambda m: m.group(0)[0] + "_" * (len(m.group(0)) - 2) + m.group(0)[-1], text
    )


def _quote_list(text: str, start: int) -> list[str]:
    """Quoted strings that follow each other from `start`, joined by commas/and/or."""
    items: list[str] = []
    pos = start
    while True:
        m = _QUOTE_RE.match(text, pos)
        if not m:
            break
        items.append(next(g for g in m.groups() if g is not None).strip())
        pos = m.end()
        sep = re.compile(r"\s*(?:,\s*(?:and|or)\s+|,\s*|\s+and\s+|\s+or\s+|&\s*)", I).match(
            text, pos
        )
        if not sep:
            break
        pos = sep.end()
    return items


# --------------------------------------------------------------------------------------
# Drafts
# --------------------------------------------------------------------------------------


@dataclass
class Draft:
    """A requirement before it is given an id."""

    description: str
    interpretation: str
    checker: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    category: Category = Category.OTHER
    severity: Severity = Severity.MAJOR
    vtype: VerificationType = D.DETERMINISTIC
    notes: str | None = None


@dataclass
class ExtractedItem:
    """A requirement plus how it was derived, for `--explain` output."""

    requirement: Requirement
    source: str
    interpretation: str


@dataclass
class ExtractionResult:
    """Requirements found in an instruction text."""

    items: list[ExtractedItem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def requirements(self) -> list[Requirement]:
        return [i.requirement for i in self.items]


@dataclass
class _Chunk:
    text: str
    items: list[str] = field(default_factory=list)
    block: str | None = None


def _det(
    description: str,
    checker: str,
    params: dict[str, Any],
    category: Category,
    severity: Severity,
    interpretation: str,
) -> Draft:
    return Draft(description, interpretation, checker, params, category, severity, D.DETERMINISTIC)


# --------------------------------------------------------------------------------------
# Splitting text into clauses
# --------------------------------------------------------------------------------------

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")
_ABBREVIATIONS = {
    "e.g",
    "i.e",
    "etc",
    "vs",
    "no",
    "fig",
    "approx",
    "cf",
    "al",
    "dr",
    "mr",
    "mrs",
    "ms",
    "st",
}
_CLAUSE_SPLIT = re.compile(
    r"\s+(?:and|but|then)\s+(?=(?:please\s+)?(?:do not|don't|never|avoid|ensure|make sure|include|use|keep|"
    r"write|cite|add|preserve|maintain|mention|state|provide|structure)\b)",
    I,
)
_SECTION_LEAD_RE = re.compile(r"\b(?:sections?|headings?|chapters?|subheadings?)\b", I)


def _chunks(raw: str) -> list[_Chunk]:
    """Group lines, attaching bullet lists and quoted blocks to a lead-in line ending in ':'."""
    lines = raw.replace("\r\n", "\n").split("\n")
    out: list[_Chunk] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        text = _BULLET_RE.sub("", stripped)
        if text.endswith(":"):
            j = i + 1
            items: list[str] = []
            block: list[str] = []
            while j < len(lines) and lines[j].strip():
                nxt = lines[j]
                if _BULLET_RE.match(nxt):
                    items.append(_BULLET_RE.sub("", nxt.strip()).rstrip(".;,"))
                elif nxt.lstrip().startswith(">"):
                    block.append(nxt.lstrip()[1:].strip())
                elif nxt.startswith(("    ", "\t")):
                    block.append(nxt.strip())
                else:
                    break
                j += 1
            if items or block:
                if items and not _SECTION_LEAD_RE.search(text):
                    out.append(_Chunk(text))  # a heading such as "Requirements:"
                    out.extend(_Chunk(item) for item in items)
                else:
                    out.append(_Chunk(text, items, "\n".join(block) or None))
                i = j
                continue
        out.append(_Chunk(text))
        i += 1
    return out


def _sentences(text: str) -> list[str]:
    masked = _mask_quotes(text)
    parts: list[str] = []
    start = 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z\"“'\[(\d])", masked):
        before = masked[start : m.start()]
        last = re.search(r"([\w.]+)\.$", before)
        if last and last.group(1).lower().rstrip(".") in _ABBREVIATIONS:
            continue
        parts.append(text[start : m.start()])
        start = m.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _clauses(sentence: str) -> list[str]:
    masked = _mask_quotes(sentence)
    parts: list[str] = []
    start = 0
    cuts = sorted(
        [(m.start(), m.end()) for m in _CLAUSE_SPLIT.finditer(masked)]
        + [(m.start(), m.end()) for m in re.finditer(r";\s+", masked)]
    )
    for lo, hi in cuts:
        parts.append(sentence[start:lo])
        start = hi
    parts.append(sentence[start:])
    return [p.strip().rstrip(".;") for p in parts if p.strip().rstrip(".;")]


# --------------------------------------------------------------------------------------
# Matchers. Each takes (clause, chunk) and returns drafts, or None if it does not apply.
# --------------------------------------------------------------------------------------

Matcher = Callable[[str, _Chunk], "list[Draft] | None"]

_NEG = r"\b(?:do not|don't|dont|never|must not|mustn't|should not|shouldn't|cannot|can't|may not|avoid|refrain from|no|without)\b"
_NEG_STRICT = r"\b(?:do not|don't|never|must not|mustn't|should not|shouldn't|cannot|can't)\b"


def _wc_desc(kind: str, n: int) -> str:
    return {
        "min": f"Document must contain at least {n:,} words",
        "max": f"Document must not exceed {n:,} words",
        "exact": f"Document must contain exactly {n:,} words",
    }[kind]


def _wc(kind: str, n: int, note: str) -> Draft:
    return _det(_wc_desc(kind, n), "word_count", {kind: n}, Category.COUNT, Severity.CRITICAL, note)


_RANGE_RE = re.compile(
    rf"(?:\b(?:between|from)\s+)?\b(?P<a>{DIGITS})\s*(?:and|to|-|–|—)\s*(?P<b>{DIGITS})[- ]?words?\b",
    I,
)
_BETWEEN_RE = re.compile(
    rf"\b(?:between|from)\s+(?P<a>{DIGITS})\s*(?:and|to|-|–)\s*(?P<b>{DIGITS})\s*words?\b", I
)
_EXACT_WC_RE = re.compile(rf"\b(?:exactly|precisely)\s+(?P<n>{DIGITS})\s*words?\b", I)
_APPROX_WC_RE = re.compile(
    rf"(?:\b(?:around|about|approximately|roughly|circa|approx\.?|nearly|close to)\s+|~\s*)(?P<n>{DIGITS})[- ]?words?\b",
    I,
)
_HYPHEN_WC_RE = re.compile(rf"\b(?P<n>{DIGITS})-words?\b", I)
_MIN_WC_RE = re.compile(
    rf"\b(?:at least|a minimum of|minimum of|minimum|min\.?|no (?:fewer|less) than|not (?:fewer|less) than|no shorter than)\s+(?P<n>{DIGITS})\s*\+?\s*words?\b"
    rf"|\b(?P<n2>{DIGITS})\s*\+?\s*words?\s*(?:or (?:more|above|over)|minimum|min\b)|\b(?P<n3>{DIGITS})\+\s*words?\b",
    I,
)
_MIN_STRICT_WC_RE = re.compile(
    rf"(?<!no )(?<!not )\b(?:more than|over|above|greater than|longer than|in excess of)\s+(?P<n>{DIGITS})\s*words?\b",
    I,
)
_MAX_WC_RE = re.compile(
    rf"\b(?:at most|a maximum of|maximum of|maximum|max\.?|no more than|not more than|up to|no longer than|not longer than|within|"
    rf"limit(?:ed)? (?:of|to)|(?:not|never|n't) (?:to )?exceed(?:ing)?|exceed(?:ing)? a maximum of)\s+(?P<n>{DIGITS})\s*words?\b"
    rf"|\b(?P<n2>{DIGITS})\s*words?\s*(?:or (?:fewer|less|under|below)|maximum|max\b|at most|limit)",
    I,
)
_MAX_STRICT_WC_RE = re.compile(
    rf"(?<!no )(?<!not )\b(?:below|under|less than|fewer than|shorter than)\s+(?P<n>{DIGITS})\s*words?\b",
    I,
)


def _apply_bound(
    clause: str, start: int, kind: str, delta: int, n: int, strict: bool
) -> tuple[str, int]:
    """Resolve a comparative into (min|max, n).

    A negation before a strict comparative flips it: "do not use more than 5" means at
    most 5, and "do not go under 500" means at least 500.
    """
    if strict and re.search(_NEG_STRICT, clause[:start], I):
        return ("max" if kind == "min" else "min"), n
    return kind, n + delta


def _first_group(m: re.Match[str]) -> int:
    return to_int(next(g for g in m.groups() if g is not None))


def match_word_count(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """Word limits: at least / at most / exactly / between / below / under."""
    m = _BETWEEN_RE.search(clause) or _RANGE_RE.search(clause)
    if m:
        lo, hi = to_int(m.group("a")), to_int(m.group("b"))
        if lo > hi:
            lo, hi = hi, lo
        return [
            _wc("min", lo, f"lower end of the range {lo:,} to {hi:,} words"),
            _wc("max", hi, f"upper end of the range {lo:,} to {hi:,} words"),
        ]
    m = _EXACT_WC_RE.search(clause)
    if m:
        return [_wc("exact", to_int(m.group("n")), "exact word count")]
    m = _APPROX_WC_RE.search(clause) or _HYPHEN_WC_RE.search(clause)
    if m:
        n = to_int(m.group("n"))
        return [
            Draft(
                f"Document length of about {n:,} words",
                "approximate length; no limit was given",
                category=Category.COUNT,
                severity=Severity.MINOR,
                vtype=D.MANUAL,
                notes=f"'{n:,} words' is approximate, so no pass/fail limit was invented. To test it, "
                "add a word_count rule with min and max.",
            )
        ]
    drafts: list[Draft] = []
    for regex, kind, delta, strict in (
        (_MIN_WC_RE, "min", 0, False),
        (_MIN_STRICT_WC_RE, "min", 1, True),
        (_MAX_WC_RE, "max", 0, False),
        (_MAX_STRICT_WC_RE, "max", -1, True),
    ):
        found = regex.search(clause)
        if found:
            kind, n = _apply_bound(clause, found.start(), kind, delta, _first_group(found), strict)
            drafts.append(_wc(kind, n, f"{kind}imum word count"))
    return drafts or None


_LIMIT_CUE = r"(?:at least|at most|no more than|not more than|maximum|max|minimum|min|up to|within|limit|exceed|under|below|exactly|no longer than|no fewer than|no less than)"
_UNSUPPORTED_UNITS_RE = re.compile(
    rf"(?:\b{_LIMIT_CUE}\b[^.;]*?\b(?P<n>{DIGITS})\s*[- ]?(?P<u>pages?|characters?|slides?|sentences?)\b|\b(?P<n2>{DIGITS})-(?P<u2>page|slide)s?\b)",
    I,
)


def match_unsupported_length(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """Page, character, slide and sentence limits cannot be measured without rendering."""
    m = _UNSUPPORTED_UNITS_RE.search(clause)
    if not m:
        return None
    n = to_int(m.group("n") or m.group("n2"))
    unit = (m.group("u") or m.group("u2")).lower().rstrip("s")
    return [
        Draft(
            f"Length requirement: {n:,} {unit}s",
            f"a {unit} limit; {unit}s cannot be counted reliably from the file",
            category=Category.COUNT,
            severity=Severity.MAJOR,
            vtype=D.UNSUPPORTED,
            notes=f"SpecGuard measures words, not {unit}s. {unit.title()} counts depend on "
            "layout and are not tested in this version.",
        )
    ]


_ELEMENT_NOUNS = {
    "bullet point": "bullets",
    "bullet": "bullets",
    "bullet item": "bullets",
    "bulleted item": "bullets",
    "list item": "list_items",
    "numbered item": "numbered_items",
    "numbered point": "numbered_items",
    "numbered list": "numbered_items",
    "heading": "headings",
    "subheading": "headings",
    "section": "headings",
    "table": "tables",
    "code block": "code_blocks",
    "code snippet": "code_blocks",
    "code example": "code_blocks",
    "paragraph": "paragraphs",
    "reference": "references",
    "source": "references",
    "bibliography entry": "references",
    "reference entry": "references",
}
_ELEMENT_RE = "|".join(sorted((re.escape(k) + "s?" for k in _ELEMENT_NOUNS), key=len, reverse=True))


def _element_of(noun: str) -> str:
    noun = noun.lower()
    return _ELEMENT_NOUNS.get(noun) or _ELEMENT_NOUNS[noun.rstrip("s")]


_FORBID_ELEM_RE = re.compile(
    rf"{_NEG}\s+(?:(?:use|using|include|including|add|adding|have|having)\s+)?(?:any\s+)?(?P<el>bullet points?|bullets|numbered lists?|tables?|headings|subheadings|code blocks?)\b",
    I,
)


def match_forbidden_element(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`Do not use bullet points` becomes a count of exactly zero."""
    m = _FORBID_ELEM_RE.search(clause)
    if not m:
        return None
    element = _element_of(m.group("el"))
    noun = element.replace("_", " ")
    return [
        _det(
            f"Document must not contain {noun}",
            "element_count",
            {"element": element, "exact": 0},
            Category.FORMATTING,
            Severity.MAJOR,
            f"zero {noun} allowed",
        )
    ]


_PUNCT_NAMES = {
    r"em[- ]?dash(?:es)?": "em_dash",
    r"en[- ]?dash(?:es)?": "en_dash",
    r"semi[- ]?colons?": "semicolon",
    r"exclamation (?:marks?|points?)": "exclamation_mark",
    r"ellipsis|ellipses": "ellipsis",
    r"ampersands?": "ampersand",
}
_PUNCT_RE = re.compile("|".join(f"(?P<p{i}>{p})" for i, p in enumerate(_PUNCT_NAMES)), I)
_PUNCT_LABELS = {
    "em_dash": "em dashes",
    "en_dash": "en dashes",
    "semicolon": "semicolons",
    "exclamation_mark": "exclamation marks",
    "ellipsis": "ellipses",
    "ampersand": "ampersands",
}


def match_forbidden_punctuation(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`Do not use em dashes` and similar."""
    cue = re.search(_NEG, clause, I)
    if not cue:
        return None
    names = list(_PUNCT_NAMES.values())
    marks: list[str] = []
    for m in _PUNCT_RE.finditer(clause, cue.end()):
        marks.append(names[int(next(k for k, v in m.groupdict().items() if v is not None)[1:])])
    if not marks:
        return None
    marks = list(dict.fromkeys(marks))
    label = " and ".join(_PUNCT_LABELS[m] for m in marks)
    if re.search(
        r"\b(?:excessive|excessively|too many|overuse|overusing|sparingly|limit the use)\b",
        clause,
        I,
    ):
        return [
            Draft(
                f"Limit {label}",
                "a limit on quantity was implied but not stated",
                category=Category.STYLE,
                severity=Severity.MINOR,
                vtype=D.MANUAL,
                notes="'Excessive' has no fixed threshold. To test it, add a forbidden_punctuation rule "
                "with max_allowed set to your limit.",
            )
        ]
    return [
        _det(
            f"Do not use {label}",
            "forbidden_punctuation",
            {"marks": marks},
            Category.STYLE,
            Severity.MAJOR,
            f"forbidden_punctuation: {', '.join(marks)}",
        )
    ]


_FORBID_QUOTED_RE = re.compile(
    rf"{_NEG}\s+(?:(?:use|using|include|including|write|writing|say|saying|mention|mentioning|introduce|introducing|"
    r"add|adding|contain|containing|put|repeat|repeating|leave|leaving|employ|employing)\s+)*"
    r"(?:(?:any|the|these|those|such)\s+)*"
    r"(?:(?P<kind>words?|phrases?|terminology|terms?|expressions?|text|strings?|wording|placeholders?)\b\s*[:\-]?\s*)?",
    I,
)
_TOKEN_RE = re.compile(
    r"\b(?:no|without|avoid|do not (?:leave|include|use))\s+(?:any\s+)?(?P<tok>TODO|TBD|FIXME|lorem ipsum)\b",
    I,
)


def match_forbidden_text(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`Do not use the phrase "X"`, `avoid the word delve`, `no TODO`."""
    for m in _FORBID_QUOTED_RE.finditer(clause):
        values = _quote_list(clause, m.end())
        kind = (m.group("kind") or "").lower()
        if not values and kind.startswith("word"):
            tail = re.match(
                r"([\w'’-]+(?:\s*(?:,\s*(?:and|or)\s+|,\s*|\s+and\s+|\s+or\s+)[\w'’-]+)*)\s*$",
                clause[m.end() :],
            )
            if tail:
                values = [v for v in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", tail.group(1)) if v]
        if values:
            whole = kind.startswith("word")
            shown = ", ".join(f'"{v}"' for v in values)
            return [
                _det(
                    f"Do not use {shown}",
                    "forbidden_text",
                    {"values": values, "whole_word": whole} if whole else {"values": values},
                    Category.TERMINOLOGY,
                    Severity.MAJOR,
                    "forbidden_text"
                    + (" (whole words, case-insensitive)" if whole else " (case-insensitive)"),
                )
            ]
    token_match = _TOKEN_RE.search(clause)
    if token_match:
        after = clause[token_match.start() :]
        tokens = list(
            dict.fromkeys(
                t.group(0) for t in re.finditer(r"\b(?:TODO|TBD|FIXME|lorem ipsum)\b", after, I)
            )
        )
        upper = all(t.isupper() for t in tokens if t.lower() != "lorem ipsum")
        params: dict[str, Any] = {"values": tokens, "whole_word": True}
        if upper and any(t.isupper() for t in tokens):
            params["case_sensitive"] = True
        return [
            _det(
                f"Do not leave placeholder text ({', '.join(tokens)})",
                "forbidden_text",
                params,
                Category.CONTENT,
                Severity.MAJOR,
                "forbidden placeholder tokens",
            )
        ]
    return None


_PRESERVE_VERB = r"(?:preserve|keep|retain|maintain|reproduce|copy|quote|include|use|leave|reuse)"
_EXACT_TAIL = r"(?:exactly|verbatim|unchanged|word[- ]for[- ]word|as (?:is|written|given|provided|supplied|approved))"
_PRESERVE_RE = re.compile(
    rf"\b{_PRESERVE_VERB}\s+(?:the\s+)?(?P<obj>[\w\s'’,-]{{1,70}}?)\s+{_EXACT_TAIL}", I
)
_PRESERVE_PASSIVE_RE = re.compile(
    rf"(?P<obj>[\w\s'’-]{{2,70}}?)\s+(?:must|should|needs to|has to)\s+(?:be\s+)?(?:appear|remain|stay|be kept|be used|be preserved|be reproduced)\s+{_EXACT_TAIL}",
    I,
)
_NO_MODIFY_RE = re.compile(
    rf"{_NEG_STRICT}\s+(?:modify|change|alter|edit|rewrite|rephrase|reword|paraphrase|amend|reorder|touch)\s+(?:any of\s+)?(?:the\s+)?(?P<obj>[^.;:]{{2,80}})",
    I,
)
_UNCHANGED_RE = re.compile(
    r"\b(?:keep|leave)\s+(?:the\s+)?(?P<obj>[^.;:]{2,80}?)\s+(?:unchanged|as is|intact|untouched)\b",
    I,
)
_NOT_CHANGED_RE = re.compile(
    r"(?P<obj>[\w\s'’-]{2,70}?)\s+(?:must|should)\s+(?:not be (?:changed|modified|altered|rewritten|edited)|remain unchanged)\b",
    I,
)

_NEEDS_TEXT_NOTE = (
    "The protected text was not given, so nothing can be compared. To test this, replace "
    "verification_type with deterministic, set checker: preserve_text, and add parameters "
    'text: "..." or baseline_file: <file>.'
)


def _clean_obj(obj: str) -> str:
    return re.sub(r"\s+", " ", obj).strip(" ,").removeprefix("the ").strip()


def match_preservation(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """Protected text: exact reuse, or "do not modify ..."."""
    exact = _PRESERVE_RE.search(clause) or _PRESERVE_PASSIVE_RE.search(clause)
    negative = (
        _NO_MODIFY_RE.search(clause)
        or _UNCHANGED_RE.search(clause)
        or _NOT_CHANGED_RE.search(clause)
    )
    m = exact or negative
    if not m:
        return None
    obj = _clean_obj(m.group("obj"))
    text: str | None = None
    quoted = _quoted(clause)
    if quoted:
        text = quoted[0]
    elif ":" in clause and clause.split(":", 1)[1].strip():
        text = clause.split(":", 1)[1].strip().strip("\"'“”")
    elif chunk.block:
        text = chunk.block
    obj = re.sub(r"^following\s+", "", obj, flags=I)
    label = obj or "protected text"
    if text:
        return [
            _det(
                f"Preserve the {label} exactly",
                "preserve_text",
                {"text": text},
                Category.PRESERVATION,
                Severity.CRITICAL,
                "protected text must appear unchanged",
            )
        ]
    return [
        Draft(
            f"Preserve the {label} exactly",
            "protected text is required but was not supplied",
            category=Category.PRESERVATION,
            severity=Severity.CRITICAL,
            vtype=D.MANUAL,
            notes=_NEEDS_TEXT_NOTE,
        )
    ]


_TITLE_TEXT_RE = re.compile(
    r"\b(?:use|set|give|name)\s+(?:the\s+)?(?:(?:document|report)\s+)?title\s+(?:of\s+|as\s+)?", I
)


def match_title(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`Use the title "X"` (without "exactly") requires that text to appear."""
    m = _TITLE_TEXT_RE.search(clause)
    if not m:
        return None
    values = _quote_list(clause, m.end())
    if not values:
        return None
    return [
        _det(
            f'Use the title "{values[0]}"',
            "required_text",
            {"values": values[:1], "case_sensitive": True},
            Category.CONTENT,
            Severity.MAJOR,
            "the title text must appear (case-sensitive)",
        )
    ]


_ELEMENT_COUNT_RE = re.compile(
    rf"(?:\b(?P<q>at least|a minimum of|minimum of|minimum|no fewer than|no less than|not fewer than|not less than|"
    rf"more than|over|above|greater than|at most|a maximum of|maximum of|maximum|no more than|not more than|up to|"
    rf"fewer than|less than|under|below|exactly|precisely)\s+)?\b(?P<n>{NUM})\s+(?:[\w-]+\s+){{0,2}}?(?P<el>{_ELEMENT_RE})\b",
    I,
)
_ELEMENT_BETWEEN_RE = re.compile(
    rf"\bbetween\s+(?P<a>{NUM})\s+and\s+(?P<b>{NUM})\s+(?:[\w-]+\s+){{0,2}}?(?P<el>{_ELEMENT_RE})\b",
    I,
)
_CITATIONS_RE = re.compile(
    rf"\b(?P<q>at least|at most|no more than|minimum of|maximum of|exactly)?\s*(?P<n>{NUM})\s+(?:[\w-]+\s+){{0,2}}?citations?\b",
    I,
)
_HAVE_VERB_RE = re.compile(
    r"\b(?:include|use|contain|have|has|provide|cite|add|list|with|feature|give|need|needs|write|create)\b",
    I,
)
_BOUND_KIND = {
    "at least": ("min", 0),
    "a minimum of": ("min", 0),
    "minimum of": ("min", 0),
    "minimum": ("min", 0),
    "no fewer than": ("min", 0),
    "no less than": ("min", 0),
    "not fewer than": ("min", 0),
    "not less than": ("min", 0),
    "more than": ("min", 1),
    "over": ("min", 1),
    "above": ("min", 1),
    "greater than": ("min", 1),
    "at most": ("max", 0),
    "a maximum of": ("max", 0),
    "maximum of": ("max", 0),
    "maximum": ("max", 0),
    "no more than": ("max", 0),
    "not more than": ("max", 0),
    "up to": ("max", 0),
    "fewer than": ("max", -1),
    "less than": ("max", -1),
    "under": ("max", -1),
    "below": ("max", -1),
    "exactly": ("exact", 0),
    "precisely": ("exact", 0),
}


_STRICT_COMPARATIVES = {
    "more than",
    "over",
    "above",
    "greater than",
    "fewer than",
    "less than",
    "under",
    "below",
}


def _element_draft(element: str, bounds: dict[str, int], source_el: str) -> Draft:
    noun = element.replace("_", " ")
    if "exact" in bounds:
        phrase = f"exactly {bounds['exact']}"
    elif "min" in bounds and "max" in bounds:
        phrase = f"between {bounds['min']} and {bounds['max']}"
    elif "min" in bounds:
        phrase = f"at least {bounds['min']}"
    else:
        phrase = f"at most {bounds['max']}"
    note = ""
    category = Category.COUNT
    if element == "headings" and source_el.lower().startswith("section"):
        note = "sections are counted as headings"
    if element == "references":
        note = "references are counted as entries under the reference-list heading"
    return _det(
        f"Document must contain {phrase} {noun}",
        "element_count",
        {"element": element, **bounds},
        category,
        Severity.MAJOR,
        note or f"count of {noun}",
    )


def match_element_count(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`include at least 30 references`, `use exactly 5 bullet points`."""
    b = _ELEMENT_BETWEEN_RE.search(clause)
    if b:
        lo, hi = sorted((to_int(b.group("a")), to_int(b.group("b"))))
        return [_element_draft(_element_of(b.group("el")), {"min": lo, "max": hi}, b.group("el"))]
    c = _CITATIONS_RE.search(clause)
    if c and _HAVE_VERB_RE.search(clause):
        return [
            Draft(
                f"Include {c.group('n')} citations",
                "in-text citations cannot be counted reliably",
                category=Category.COUNT,
                severity=Severity.MAJOR,
                vtype=D.UNSUPPORTED,
                notes="In-text citations are not detected in this version. To count reference-list "
                "entries instead, use an element_count rule with element: references.",
            )
        ]
    m = _ELEMENT_COUNT_RE.search(clause)
    if not m:
        return None
    q = (m.group("q") or "").lower()
    n = to_int(m.group("n"))
    element = _element_of(m.group("el"))
    if q:
        kind, delta = _BOUND_KIND[q]
        kind, n = _apply_bound(clause, m.start(), kind, delta, n, q in _STRICT_COMPARATIVES)
        return [_element_draft(element, {kind: n}, m.group("el"))]
    if _HAVE_VERB_RE.search(clause):
        return [
            Draft(
                f"Include {n} {element.replace('_', ' ')}",
                "a quantity without at least/at most/exactly",
                category=Category.COUNT,
                severity=Severity.MAJOR,
                vtype=D.MANUAL,
                notes="It is unclear whether this means exactly, at least or at most. To test it, add an "
                "element_count rule with the meaning you intend.",
            )
        ]
    return None


_OCCURRENCE_RE = re.compile(
    rf"\b(?:mention|use|include|say|repeat|reference|write|contain|feature)\s+(?P<target>.+?)\s+"
    rf"(?:(?P<q>at least|at most|no more than|no fewer than|no less than|not more than|not fewer than|exactly|a maximum of|a minimum of|up to)\s+)?"
    rf"(?:(?P<n>{NUM})\s+times?|(?P<w>once|twice|thrice))\b",
    I,
)
_WORDY = {"once": 1, "twice": 2, "thrice": 3}


def match_occurrences(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`mention climate change at least twice`."""
    m = _OCCURRENCE_RE.search(clause)
    if not m:
        return None
    target = m.group("target").strip()
    quoted = _quoted(target)
    if quoted:
        target = quoted[0]
    else:
        target = re.sub(
            r"^(?:the\s+)?(?:(?:word|phrase|term)s?\s+)?(?:the\s+)?", "", target, flags=I
        ).strip()
        if not target or len(target.split()) > 6 or re.search(_ELEMENT_RE, target, I):
            return None
    n = _WORDY[m.group("w").lower()] if m.group("w") else to_int(m.group("n"))
    q = (m.group("q") or "").lower()
    if not q:
        return [
            Draft(
                f'Use "{target}" {n} time(s)',
                "a count without at least/at most/exactly",
                category=Category.TERMINOLOGY,
                severity=Severity.MAJOR,
                vtype=D.MANUAL,
                notes="It is unclear whether this means exactly, at least or at most. To test it, add an "
                "occurrences rule with the meaning you intend.",
            )
        ]
    kind, delta = _BOUND_KIND[q]
    kind, n = _apply_bound(clause, m.start(), kind, delta, n, q in _STRICT_COMPARATIVES)
    phrase = {"min": f"at least {n}", "max": f"at most {n}", "exact": f"exactly {n}"}[kind]
    return [
        _det(
            f'"{target}" must appear {phrase} times',
            "occurrences",
            {"text": target, kind: n},
            Category.TERMINOLOGY,
            Severity.MAJOR,
            f"occurrences of the phrase, {kind} {n}",
        )
    ]


_SECTION_NAMES = [
    "executive summary",
    "table of contents",
    "literature review",
    "research questions",
    "research objectives",
    "acknowledgements",
    "acknowledgments",
    "introduction",
    "background",
    "methodology",
    "methods",
    "findings",
    "results",
    "discussion",
    "conclusions",
    "conclusion",
    "recommendations",
    "references",
    "bibliography",
    "abstract",
    "appendix",
    "appendices",
    "limitations",
    "objectives",
    "overview",
    "installation",
    "usage",
    "summary",
    "keywords",
    "glossary",
    "contributing",
    "license",
    "licence",
    "works cited",
    "reference list",
]
_NAME_RE = "|".join(sorted((re.escape(n) for n in _SECTION_NAMES), key=len, reverse=True))
_REFERENCE_GROUP = ["References", "Reference list", "Bibliography", "Works cited"]
_ALTERNATIVES = {
    "references": _REFERENCE_GROUP,
    "bibliography": _REFERENCE_GROUP,
    "reference list": _REFERENCE_GROUP,
    "works cited": _REFERENCE_GROUP,
    "conclusion": ["Conclusion", "Conclusions"],
    "conclusions": ["Conclusion", "Conclusions"],
    "methodology": ["Methodology", "Methods"],
    "methods": ["Methodology", "Methods"],
    "acknowledgements": ["Acknowledgements", "Acknowledgments"],
    "acknowledgments": ["Acknowledgements", "Acknowledgments"],
    "license": ["License", "Licence"],
    "licence": ["License", "Licence"],
    "results": ["Results", "Findings"],
}
_HEADING_LEAD_RE = re.compile(
    r"\b(?:include|contain|have|use|with|add|cover|feature|organi[sz]e (?:it )?(?:into|with|as)|structure(?:d)? "
    r"(?:it |the \w+ )?(?:into|with|as)|divide(?:d)? (?:it |the \w+ )?into|separate(?:d)? (?:it )?into)\s+"
    r"(?:the\s+)?(?:following\s+|these\s+|named\s+|below\s+)?(?:(?:\w+\s+){0,2}?)(?:sections?|headings?|chapters?|subheadings?)\b\s*"
    r"(?:named|called|titled|below|are|:|-|—)?\s*(?P<list>.*)$",
    I,
)
_LIST_SPLIT_RE = re.compile(r"\s*(?:,\s*(?:and|or)\s+|,\s*|;\s*|\s+and\s+|\s+&\s+|\s+or\s+)", I)
_PREPOSITIONS = (
    "on ",
    "about ",
    "for ",
    "that ",
    "which ",
    "covering ",
    "to ",
    "of ",
    "in ",
    "where ",
    "explaining ",
    "describing ",
)


def _heading_drafts(names: list[str], how: str) -> list[Draft]:
    drafts = []
    for name in names:
        group = _ALTERNATIVES.get(name.lower())
        headings: list[Any] = [group] if group else [name]
        drafts.append(
            _det(
                f"Include the {name} section",
                "required_section",
                {"headings": headings},
                Category.STRUCTURE,
                Severity.MAJOR,
                how,
            )
        )
    return drafts


def match_section_list(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`include the sections A, B and C`, or a bulleted list under such a lead-in."""
    m = _HEADING_LEAD_RE.search(clause)
    if not m:
        return None
    quoted = _quote_list(clause, m.start("list")) or None
    if quoted:
        names = quoted
    else:
        tail = m.group("list").strip().rstrip(".")
        if chunk.items:
            names = [i.strip().strip("\"'“”") for i in chunk.items]
        else:
            if not tail or tail.lower().startswith(_PREPOSITIONS):
                return None
            names = [p.strip().strip("\"'“”") for p in _LIST_SPLIT_RE.split(tail) if p.strip()]
    names = [re.sub(r"^(?:an?|the)\s+", "", n, flags=I) for n in names]
    if not names or any(not n or len(n.split()) > 6 or re.search(r"[.!?]", n) for n in names):
        return None
    return _heading_drafts(names, "named heading must be present")


_QUOTED_HEADING_RE = re.compile(
    r"\b(?:use|include|add|have|with|title(?:d)?|call(?:ed)?)\s+(?:an?\s+|the\s+)?(?:section|heading|chapter|subheading)s?\s*"
    r"(?:(?:titled|called|named|labell?ed)\s+)?",
    I,
)


def match_quoted_heading(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`use the heading "Methodology"`."""
    m = _QUOTED_HEADING_RE.search(clause)
    if not m:
        return None
    names = _quote_list(clause, m.end())
    if not names:
        return None
    return [
        _det(
            f'Include a "{n}" heading',
            "required_section",
            {"headings": [n]},
            Category.STRUCTURE,
            Severity.MAJOR,
            "exact heading text",
        )
        for n in names
    ]


_NAMED_SECTION_RE = re.compile(
    rf"\b(?:include|add|provide|contain|have|has|need|needs|must have|should have|with|end with|begin with|start with)\s+"
    rf"(?:an?\s+|the\s+|some\s+)?(?P<name>{_NAME_RE})\b",
    I,
)
_NAME_TAIL_OK_RE = re.compile(
    r"^(?:\s+(?:section|heading|chapter))?\s*(?:$|[,.;:]|\s+(?:at|in|near|to|and|or|with|that|which)\b)",
    I,
)


def match_named_section(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`include a conclusion`, `must include references`. Only well-known section names."""
    m = _NAMED_SECTION_RE.search(clause)
    if not m or not _NAME_TAIL_OK_RE.match(clause[m.end() :]):
        return None
    names = [m.group("name")]
    pos = m.end()
    more = re.compile(
        rf"(?:\s+(?:section|heading|chapter))?\s*(?:,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+&\s+)(?:an?\s+|the\s+)?(?P<name>{_NAME_RE})\b",
        I,
    )
    while True:
        nxt = more.match(clause, pos)
        if not nxt:
            break
        names.append(nxt.group("name"))
        pos = nxt.end()
    if not _NAME_TAIL_OK_RE.match(clause[pos:]):
        return None
    return _heading_drafts(
        [n.title() if n.islower() else n for n in names], "well-known section name"
    )


_REQUIRED_QUOTED_RE = re.compile(
    r"\b(?:include|contain|mention|use|say|feature|add|have|cite|reference)\s+(?:the\s+)?"
    r"(?:(?:exact\s+)?(?P<kind>words?|phrases?|terminology|terms?|expressions?|text|strings?)\b\s*[:\-]?\s*)?",
    I,
)
_REQ_QUOTED_LEAD_RE = re.compile(
    r"\b(?:must|should|need to|needs to|has to|shall|always|please|ensure|make sure)\b|^(?:include|contain|mention|use|say|add|cite)\b",
    I,
)


def match_required_text(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`include the phrase "X"`, `use the terminology "Y"`."""
    for m in _REQUIRED_QUOTED_RE.finditer(clause):
        values = _quote_list(clause, m.end())
        if values and _REQ_QUOTED_LEAD_RE.search(clause):
            whole = (m.group("kind") or "").lower().startswith("word")
            shown = ", ".join(f'"{v}"' for v in values)
            params: dict[str, Any] = {"values": values}
            if whole:
                params["whole_word"] = True
            return [
                _det(
                    f"Include {shown}",
                    "required_text",
                    params,
                    Category.TERMINOLOGY,
                    Severity.MAJOR,
                    "required_text, all values, case-insensitive",
                )
            ]
    return None


_FILE_KINDS: list[tuple[str, str]] = [
    (r"word (?:document|file)|docx(?: file| document)?|\.docx|microsoft word|ms word", "docx"),
    (r"markdown(?: file| document)?|\.md\b", "md"),
    (r"plain[- ]?text(?: file)?|\.txt\b|txt file|text file", "txt"),
    (r"pdf(?: file| document)?|\.pdf\b", "pdf"),
]
_FILE_CUE_RE = re.compile(
    r"\b(?:deliver|provide|save|export|output|submit|produce|write|written|return|format|formatted|must be|should be|supply|as|in)\b",
    I,
)
_FILE_RE = re.compile(
    r"\b(?:(?:as|in|into|to)\s+(?:an?\s+)?|be\s+(?:an?\s+)?|(?:formatted|format)\s+(?:as|in)\s+(?:an?\s+)?)"
    + "(?P<t>"
    + "|".join(f"(?:{p})" for p, _ in _FILE_KINDS)
    + ")",
    I,
)


def match_file_type(clause: str, chunk: _Chunk) -> list[Draft] | None:
    """`deliver as a Word document`."""
    m = _FILE_RE.search(clause)
    if not m or not _FILE_CUE_RE.search(
        clause[: m.start()] + " " + clause[m.start() : m.start() + 4]
    ):
        return None
    text = m.group("t")
    for pattern, ext in _FILE_KINDS:
        if re.fullmatch(pattern, text, I):
            if ext == "pdf":
                return [
                    Draft(
                        "Deliver as a PDF file",
                        "PDF is not a supported input format",
                        category=Category.FILE,
                        severity=Severity.MAJOR,
                        vtype=D.UNSUPPORTED,
                        notes="SpecGuard 0.1 reads .txt, .md and .docx only, so a PDF cannot be audited.",
                    )
                ]
            return [
                _det(
                    f"File must be a .{ext} file",
                    "file_type",
                    {"extensions": [ext]},
                    Category.FILE,
                    Severity.MAJOR,
                    f"file extension .{ext}",
                )
            ]
    return None


# Matchers run in this order. Specific patterns come before general ones.
MATCHERS: list[Matcher] = [
    match_preservation,
    match_title,
    match_word_count,
    match_unsupported_length,
    match_forbidden_element,
    match_forbidden_punctuation,
    match_forbidden_text,
    match_element_count,
    match_occurrences,
    match_quoted_heading,
    match_section_list,
    match_named_section,
    match_required_text,
    match_file_type,
]

# --------------------------------------------------------------------------------------
# Fallback: keep instructions we cannot test, without guessing a rule
# --------------------------------------------------------------------------------------

_IMPERATIVES = (
    "write",
    "make",
    "use",
    "keep",
    "ensure",
    "include",
    "avoid",
    "maintain",
    "adopt",
    "be",
    "add",
    "provide",
    "cite",
    "follow",
    "structure",
    "format",
    "explain",
    "describe",
    "discuss",
    "analyse",
    "analyze",
    "summarise",
    "summarize",
    "address",
    "cover",
    "present",
    "create",
    "produce",
    "give",
    "state",
    "list",
    "define",
    "compare",
    "evaluate",
    "support",
    "limit",
    "focus",
    "highlight",
    "emphasise",
    "emphasize",
    "organise",
    "organize",
    "begin",
    "start",
    "end",
    "conclude",
    "open",
    "close",
    "remember",
    "always",
    "never",
    "do not",
    "don't",
    "please",
    "aim",
    "show",
    "demonstrate",
    "justify",
    "review",
    "proofread",
    "check",
    "tailor",
    "adapt",
    "incorporate",
    "refer",
    "mention",
    "translate",
    "rewrite",
    "answer",
    "reference",
    "ensure",
    "consider",
    "prefer",
    "stick",
)
_MODAL_RE = re.compile(
    r"\b(?:must|should|shall|need to|needs to|has to|have to|required to|ought to|make sure|ensure)\b",
    I,
)
_LEAD_RE = re.compile(
    r"^(?:please\s+|also\s+|and\s+|then\s+|finally\s+|you\s+(?:should|must|need to|will need to|have to)\s+)+",
    I,
)
_UNSUPPORTED_RE = re.compile(
    r"\b(?:font|typeface|margins?|line spacing|double[- ]spaced|single[- ]spaced|header|footer|page numbers?|footnotes?|"
    r"endnotes?|apa|harvard|mla|chicago|vancouver|ieee|referencing style|citation style|justified|indent|"
    r"times new roman|arial|calibri|helvetica|garamond|cambria|\d{1,2}\s*(?:pt|point))\b",
    I,
)
_MANUAL_RE = re.compile(
    r"\b(?:visual(?:ly)?|appealing|beautiful|attractive|aesthetic|design(?:ed)?|layout|images?|photos?|colou?rs?|"
    r"logo|slides?|presentation|send|email|deadline|sign(?:ed)?|approve[ds]?|submit|upload|share)\b",
    I,
)
_STYLE_RE = re.compile(
    r"\b(?:tone|style|voice|register|english|spelling|formal|informal|professional|engaging|academic|scholarly|clear|"
    r"concise|readable|readability|persuasive|friendly|plain|jargon|master'?s|phd|student|audience|reading level|"
    r"grammar|fluent|natural|human|polished|compelling)\b",
    I,
)
_CONTENT_RE = re.compile(
    r"\b(?:cover|discuss|explain|address|describe|include|mention|analy[sz]e|summari[sz]e|compare|evaluate|argument|reasoning|evidence|objectives?)\b",
    I,
)


def _is_instruction(clause: str) -> bool:
    if clause.endswith("?") or len(clause.split()) < 3:
        return False
    stripped = _LEAD_RE.sub("", clause).lower()
    if any(stripped == v or stripped.startswith(v + " ") for v in _IMPERATIVES):
        return True
    return bool(_MODAL_RE.search(clause) or re.search(_NEG_STRICT, clause, I))


def fallback(clause: str) -> Draft:
    """Classify an instruction we cannot turn into a rule. Never returns a deterministic draft."""
    text = clause.strip().rstrip(".")
    if _UNSUPPORTED_RE.search(clause):
        return Draft(
            text[0].upper() + text[1:],
            "a formatting or referencing-style rule with no checker yet",
            category=Category.FORMATTING,
            severity=Severity.MAJOR,
            vtype=D.UNSUPPORTED,
            notes="This could be tested in principle, but this version has no checker for it.",
        )
    if _MANUAL_RE.search(clause):
        return Draft(
            text[0].upper() + text[1:],
            "needs a person to judge or act",
            category=Category.OTHER,
            severity=Severity.MINOR,
            vtype=D.MANUAL,
            notes="This requirement needs human review.",
        )
    if _STYLE_RE.search(clause):
        category, severity = Category.STYLE, Severity.MINOR
    elif _CONTENT_RE.search(clause):
        category, severity = Category.CONTENT, Severity.MAJOR
    else:
        category, severity = Category.SEMANTIC, Severity.MINOR
    return Draft(
        text[0].upper() + text[1:],
        "needs language understanding to judge",
        category=category,
        severity=severity,
        vtype=D.SEMANTIC,
        notes="Needs semantic judgement. No deterministic check was invented for it.",
    )


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------


def _requirement_from(draft: Draft, req_id: str, source: str) -> Requirement:
    return Requirement(
        id=req_id,
        description=draft.description,
        source_text=source,
        category=draft.category,
        severity=draft.severity,
        verification_type=draft.vtype,
        checker=draft.checker,
        parameters=draft.parameters,
        notes=draft.notes,
    )


def extract_requirements(text: str, *, id_prefix: str = "SG") -> ExtractionResult:
    """Find candidate requirements in instruction text.

    Requirement ids are `SG001`, `SG002`, ... in reading order, so the same text always
    yields the same ids.
    """
    result = ExtractionResult()
    counter = 0
    for chunk in _chunks(text):
        sentences = _sentences(chunk.text)
        if chunk.items and _SECTION_LEAD_RE.search(chunk.text):
            sentences = [f"{chunk.text} {', '.join(chunk.items)}"]
        for sentence in sentences:
            for clause in _clauses(sentence):
                drafts: list[Draft] | None = None
                for matcher in MATCHERS:
                    drafts = matcher(clause, chunk)
                    if drafts:
                        break
                if not drafts:
                    if not _is_instruction(clause):
                        result.skipped.append(clause)
                        continue
                    drafts = [fallback(clause)]
                for draft in drafts:
                    counter += 1
                    req = _requirement_from(draft, f"{id_prefix}{counter:03d}", clause)
                    result.items.append(ExtractedItem(req, clause, draft.interpretation))
    return result
