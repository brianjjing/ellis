"""Layer-4 keyword backstop and sensitive-number redaction.

Runs in the liaison handler on every final transcript before the LLM, and again server-side on stored text.
Matching is accent-insensitive. The English/Spanish lists (stop_list.yaml, flag_list.yaml) apply to every
conversation, on word boundaries; with `lang`, that language's lists (keywords_i18n.yaml) apply too, matched
at the start of a word in Latin, Cyrillic, Greek or Georgian script, anywhere in any other script.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

from ..config import yaml_config

DIGIT_RUN = re.compile(r"(?:\d[\s\-.]?){7,}\d")
# a full date or a year range ("1995-09-11", "09/11/1995", "2015-2019") is not an ID number; the month, day and
# year ranges keep SSN (3-2-4) and A-number shapes out
_MD = r"(?:0?[1-9]|[12]\d|3[01])"
DATE = re.compile(rf"\b(?:(?:19|20)\d\d[-/. ]{_MD}[-/. ]{_MD}|{_MD}[-/. ]{_MD}[-/. ](?:19|20)\d\d"
                  rf"|(?:19|20)\d\d ?[-–] ?(?:19|20)\d\d)\b")
SPOKEN_DIGITS = {
    "cero", "uno", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve",
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
}
# Chinese and Japanese numerals, read as digits (Python's \d already covers other scripts' decimal digits)
_HAN_DIGITS = str.maketrans("零〇一二两三四五六七八九", "001223456789")
# scripts written with spaces between words, where a stem must start a word
_WORD_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK", "GEORGIAN")


# letters NFKD doesn't take apart, spelled the way stems are written (Vietnamese đ, Polish ł, Danish ø, ...)
_UNSPLIT = str.maketrans({"đ": "d", "Đ": "d", "ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae",
                          "œ": "oe", "Œ": "oe", "ß": "ss", "ı": "i", "ð": "d", "þ": "th", "ħ": "h"})


def fold(text: str) -> str:
    """Unicode NFKD, strip accents, lowercase, collapse spaces."""
    t = unicodedata.normalize("NFKD", text.translate(_UNSPLIT))
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


def _word_script(stem: str) -> bool:
    return all(unicodedata.name(c, "").startswith(_WORD_SCRIPTS) for c in stem if c.isalpha())


@lru_cache
def _lang_patterns(lang: str, kind: str) -> list[tuple[str, re.Pattern]]:
    """One language's stop or flag stems: a prefix of a word where words have spaces (catches inflections),
    anywhere in the text otherwise (no spaces, or prefixes and vowel signs joined to the word)."""
    cfg = ((yaml_config("keywords_i18n.yaml") or {}).get(lang) or {}).get(kind) or {}
    out = []
    for cat, stems in cfg.items():
        for stem in stems or []:
            s = fold(str(stem))
            if s:
                out.append((cat, re.compile((r"\b" if _word_script(s) else "") + re.escape(s))))
    return out


def _all_patterns(base: str, kind: str, lang: str | None) -> Iterable[tuple[str, re.Pattern]]:
    yield from _patterns(base)
    if lang and lang not in ("en", "es"):
        yield from _lang_patterns(lang, kind)


def stop_hit(text: str, lang: str | None = None) -> str | None:
    """Return the stop-list category matched by this transcript, if any (first configured category wins)."""
    f = fold(text)
    for cat, pat in _all_patterns("stop_list.yaml", "stop", lang):
        if pat.search(f):
            return cat
    return None


def flag_hits(text: str, lang: str | None = None) -> list[str]:
    f = fold(text)
    cats = []
    for cat, pat in _all_patterns("flag_list.yaml", "flag", lang):
        if pat.search(f) and cat not in cats:
            cats.append(cat)
    return cats


@lru_cache
def _spoken_digits(lang: str | None) -> frozenset[str]:
    words = ((yaml_config("keywords_i18n.yaml") or {}).get(lang) or {}).get("digits") or [] if lang else []
    return frozenset(SPOKEN_DIGITS | {fold(str(w)) for w in words})


def has_sensitive_number(text: str, lang: str | None = None) -> bool:
    """A run of 7+ digits (typed or spoken word-by-word) looks like an A-number, SSN or case number; a date doesn't."""
    text = DATE.sub(" date ", text.translate(_HAN_DIGITS))
    if DIGIT_RUN.search(text):
        return True
    words = fold(text).split()
    digits = _spoken_digits(lang)
    run = 0
    for w in words:
        if w in digits or w.isdigit():
            run += len(w) if w.isdigit() else 1
            if run >= 7:
                return True
        else:
            run = 0
    return False


def redact_numbers(text: str, lang: str | None = None) -> str:
    t = DIGIT_RUN.sub(lambda m: m[0] if DATE.fullmatch(m[0]) else "[REDACTED_NUMBER]", text)
    if has_sensitive_number(t, lang):
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
