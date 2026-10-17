"""spelling_variant: the document uses British or American spelling, not the other.

This is a word-list check, not a spell checker. It looks for spellings that belong to the
*other* variant, from a built-in list of common pairs. A failure is reliable (that spelling is
in the text); a pass means only that none of the listed spellings were found, so it carries a
lower confidence and the evidence says how many pairs were checked.

Oxford spelling (`organize` in British English) is accepted: `-ize` is never reported in a
British document, but `-ise` is reported in an American one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from specguard.models.document import Document
from specguard.models.requirement import Requirement
from specguard.models.result import CheckResult
from specguard.rules.base import RuleChecker, register_rule
from specguard.rules.params import (
    ParameterError,
    Scope,
    get_choice,
    get_str_list,
    reject_unknown,
)
from specguard.utils.matching import Hit, sample_lines
from specguard.utils.text import plural

# (American stem, British stem). A stem takes any ending from _SUFFIX, so one pair covers
# `colour`, `colours`, `coloured`, `colourful`...
_PAIRS: list[tuple[str, str]] = [
    ("color", "colour"),
    ("favor", "favour"),
    ("honor", "honour"),
    ("labor", "labour"),
    ("neighbor", "neighbour"),
    ("behavior", "behaviour"),
    ("flavor", "flavour"),
    ("harbor", "harbour"),
    ("humor", "humour"),
    ("rumor", "rumour"),
    ("vapor", "vapour"),
    ("savior", "saviour"),
    ("endeavor", "endeavour"),
    ("armor", "armour"),
    ("odor", "odour"),
    ("tumor", "tumour"),
    ("vigor", "vigour"),
    ("rigor", "rigour"),
    ("candor", "candour"),
    ("splendor", "splendour"),
    ("demeanor", "demeanour"),
    ("center", "centre"),
    ("theater", "theatre"),
    ("liter", "litre"),
    ("fiber", "fibre"),
    ("caliber", "calibre"),
    ("somber", "sombre"),
    ("specter", "spectre"),
    ("kilometer", "kilometre"),
    ("centimeter", "centimetre"),
    ("millimeter", "millimetre"),
    ("defense", "defence"),
    ("offense", "offence"),
    ("pretense", "pretence"),
    ("catalog", "catalogue"),
    ("analyz", "analys"),
    ("paralyz", "paralys"),
    ("catalyz", "catalys"),
    ("skeptic", "sceptic"),
    ("aluminum", "aluminium"),
    ("plow", "plough"),
    ("mold", "mould"),
    ("pajama", "pyjama"),
    ("sulfur", "sulphur"),
    ("cozy", "cosy"),
    ("donut", "doughnut"),
    ("aging", "ageing"),
    ("esthetic", "aesthetic"),
    ("anemi", "anaemi"),
    ("pediatric", "paediatric"),
    ("orthopedic", "orthopaedic"),
    ("maneuver", "manoeuvre"),
    ("diarrhea", "diarrhoea"),
    ("leukemia", "leukaemia"),
    ("mustache", "moustache"),
    ("airplane", "aeroplane"),
    ("jewelry", "jewellery"),
    ("enrollment", "enrolment"),
    ("fulfillment", "fulfilment"),
    ("installment", "instalment"),
    ("skillful", "skilful"),
    ("willful", "wilful"),
    ("counselor", "counsellor"),
    ("marvelous", "marvellous"),
]
# Doubled-consonant forms: American single l, British double l.
_DOUBLED = [
    ("traveled", "travelled"),
    ("traveling", "travelling"),
    ("traveler", "traveller"),
    ("canceled", "cancelled"),
    ("canceling", "cancelling"),
    ("labeled", "labelled"),
    ("labeling", "labelling"),
    ("modeled", "modelled"),
    ("modeling", "modelling"),
    ("fueled", "fuelled"),
    ("fueling", "fuelling"),
    ("signaled", "signalled"),
    ("signaling", "signalling"),
    ("leveled", "levelled"),
    ("leveling", "levelling"),
    ("enroll", "enrol"),
    ("fulfill", "fulfil"),
]
# Stems that take -ize (American, and optional Oxford British) or -ise (British).
_IZE = [
    "organ", "real", "recogn", "summar", "emphas", "priorit", "minim", "maxim", "util", "final",
    "author", "critic", "apolog", "standard", "special", "custom", "capital", "categor",
    "character", "harmon", "modern", "normal", "optim", "stabil", "visual", "familiar", "mobil",
    "legal", "fertil", "general", "memor", "central", "sympath", "symbol", "subsid", "digit",
    "institution", "personal", "popular", "equal", "commercial", "social", "national",
    "industrial", "monopol", "hospital", "rational", "revolution", "urban", "verbal", "moral",
    "neutral", "radical", "stigmat", "styl", "tranquil",
]  # fmt: skip
_IZE_END = r"(?:e|es|ed|ing|ation|ations|er|ers)"
_SUFFIX = (
    r"(?:s|es|d|ed|ing|er|ers|ful|less|ly|ist|ists|ism|y|ies|able|ite|ites|ary|ous|"
    r"ation|ations|ment|ments)?"
)
_LEFT = r"(?<![A-Za-z])"
_RIGHT = r"(?![A-Za-z])"


def _compile(forms: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(forms), re.IGNORECASE)


def _stem_forms(stems: list[str]) -> list[str]:
    return [_LEFT + re.escape(s) + _SUFFIX + _RIGHT for s in stems]


def _build() -> dict[str, tuple[re.Pattern[str], int]]:
    """Patterns that find the *wrong* variant for each target variant, and the pair count."""
    us_stems = [us for us, uk in _PAIRS if uk]
    uk_stems = [uk for us, uk in _PAIRS if uk]
    us_forms = _stem_forms(us_stems) + [_LEFT + re.escape(us) + _RIGHT for us, _ in _DOUBLED]
    uk_forms = _stem_forms(uk_stems) + [_LEFT + re.escape(uk) + _RIGHT for _, uk in _DOUBLED]
    # `-ise` is British only; `-ize` is American and also accepted as Oxford British.
    uk_forms += [_LEFT + s + "is" + _IZE_END + _RIGHT for s in _IZE]
    n_pairs = len(us_stems) + len(_DOUBLED) + len(_IZE)
    return {
        # British target: report American spellings (but not -ize).
        "british": (_compile(us_forms), n_pairs),
        # American target: report British spellings, including -ise.
        "american": (_compile(uk_forms), n_pairs),
    }


_PATTERNS = _build()
# Double-quoted spans (straight or curly) on one line.
_QUOTED_RE = re.compile('"[^"\n]+"|“[^”\n]+”')


@dataclass
class _Config:
    variant: str
    allow: list[str]
    scope: Scope


@register_rule
class SpellingVariantRule(RuleChecker):
    rule_type = "spelling_variant"
    summary = "The document uses British or American spelling (word-list check)."
    parameter_help: ClassVar[dict[str, str]] = {
        "variant": "`british` or `american`.",
        "allow": "Words to ignore, such as a proper name that keeps the other spelling.",
        "exclude_code_blocks / exclude_sections": "Skip parts of the document.",
    }

    def parse(self, parameters: Mapping[str, Any]) -> _Config:
        reject_unknown(parameters, ("variant", "allow", *Scope.KEYS))
        if "variant" not in parameters:
            raise ParameterError("'variant' is required")
        return _Config(
            variant=get_choice(parameters, "variant", ("british", "american"), "british"),
            allow=get_str_list(parameters, "allow", required=False),
            scope=Scope.from_params(parameters),
        )

    def check(self, document: Document, requirement: Requirement) -> CheckResult:
        cfg = self.parse(requirement.parameters)
        pattern, n_pairs = _PATTERNS[cfg.variant]
        allowed = {a.casefold() for a in cfg.allow}
        units, notes = cfg.scope.select(document)
        found: Counter[str] = Counter()
        quoted: Counter[str] = Counter()
        hits: list[Hit] = []
        for unit in units:
            flat = unit.flat
            spans = [m.span() for m in _QUOTED_RE.finditer(flat)]
            for m in pattern.finditer(flat):
                word = m.group(0)
                if word.casefold() in allowed:
                    continue
                if any(lo <= m.start() and m.end() <= hi for lo, hi in spans):
                    quoted[word.casefold()] += 1
                    continue
                found[word.casefold()] += 1
                hits.append(Hit(word, word, unit.locate(m.start(), m.end())))
        other = "American" if cfg.variant == "british" else "British"
        expected = f"{cfg.variant.capitalize()} spelling throughout"
        basis = (
            f"Checked against a built-in list of {n_pairs} spelling pairs; "
            "words that are not on the list were not examined."
        )
        if quoted:
            shown_q = ", ".join(f'"{w}" x {c}' for w, c in quoted.most_common(5))
            notes = [
                f"Ignored {other} spellings inside quotation marks (titles and quotations keep "
                f"their own spelling): {shown_q}.",
                *notes,
            ]
        details: dict[str, Any] = {
            "other_variant_words": dict(found),
            "ignored_in_quotes": dict(quoted),
            "pairs_checked": n_pairs,
        }
        if not found:
            return self.passed(
                requirement,
                f"No {other} spellings from the word list were found.",
                expected=expected,
                actual=f"0 {other} spellings found",
                evidence=[basis, *notes],
                confidence=0.75,
                details=details,
            )
        shown = ", ".join(f'"{w}" x {c}' for w, c in found.most_common(10))
        total = sum(found.values())
        return self.failed(
            requirement,
            f"Found {plural(total, other + ' spelling')}: {shown}.",
            expected=expected,
            actual=plural(total, other + " spelling"),
            evidence=[
                *sample_lines(hits),
                "A proper name may keep its own spelling; add it to `allow` if so.",
                basis,
                *notes,
            ],
            locations=[h.location for h in hits],
            remediation_hint=f"Change each listed word to its {cfg.variant.capitalize()} spelling.",
            details=details,
        )
