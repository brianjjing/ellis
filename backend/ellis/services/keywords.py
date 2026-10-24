"""Layer-4 keyword backstop and sensitive-number redaction.

Runs in the liaison handler on every final transcript before the LLM, and again server-side on stored text.
Matching is accent-insensitive, on word boundaries.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from ..config import yaml_config

DIGIT_RUN = re.compile(r"(?:\d[\s\-.]?){7,}\d")
SPOKEN_DIGITS = {
    "cero", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
}


def fold(text: str) -> str:
    """Unicode NFKD, strip accents, lowercase, collapse spaces."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


@lru_cache
def _patterns(name: str) -> list[tuple[str, re.Pattern]]:
    cfg = yaml_config(name) or {}
    out = []
    for cat, stems in cfg.items():
        for stem in stems:
            out.append((cat, re.compile(r"\b" + re.escape(fold(stem)) + r"\b")))
    return out


def stop_hit(text: str) -> str | None:
    """Return the stop-list category matched by this transcript, if any (first configured category wins)."""
    f = fold(text)
    for cat, pat in _patterns("stop_list.yaml"):
        if pat.search(f):
            return cat
    return None


def flag_hits(text: str) -> list[str]:
    f = fold(text)
    cats = []
    for cat, pat in _patterns("flag_list.yaml"):
        if pat.search(f) and cat not in cats:
            cats.append(cat)
    return cats


def has_sensitive_number(text: str) -> bool:
    """A run of 7+ digits (typed or spoken word-by-word) looks like an A-number, SSN or case number."""
    if DIGIT_RUN.search(text):
        return True
    words = fold(text).split()
    run = 0
    for w in words:
        if w in SPOKEN_DIGITS or w.isdigit():
            run += len(w) if w.isdigit() else 1
            if run >= 7:
                return True
        else:
            run = 0
    return False


def redact_numbers(text: str) -> str:
    t = DIGIT_RUN.sub("[REDACTED_NUMBER]", text)
    if has_sensitive_number(t):
        return "[REDACTED_NUMBER]"
    return t


def name_tokens(name: str) -> set[str]:
    return set(fold(name).split())


def names_match(a_given: str, a_family: str, b_given: str, b_family: str) -> dict[str, bool]:
    """Compare token sets for given and family names separately (accent-folded)."""
    return {
        "given": bool(name_tokens(a_given) & name_tokens(b_given)) and (
            name_tokens(a_given) <= name_tokens(b_given) or name_tokens(b_given) <= name_tokens(a_given)),
        "family": name_tokens(a_family) == name_tokens(b_family),
    }
