"""English answer parsing for the liaison: dates, yes/no, hedges, numbers, names, enums.

Mirrors spanish.py function-for-function so the liaison can dispatch to either by language. The liaison only
parses what the applicant said into a canonical value; it never computes with dates.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..services.keywords import fold

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
UNITS = {
    "zero": 0, "one": 1, "first": 1, "two": 2, "second": 2, "three": 3, "third": 3, "four": 4, "fourth": 4,
    "five": 5, "fifth": 5, "six": 6, "sixth": 6, "seven": 7, "seventh": 7, "eight": 8, "eighth": 8, "nine": 9,
    "ninth": 9, "ten": 10, "tenth": 10, "eleven": 11, "eleventh": 11, "twelve": 12, "twelfth": 12,
    "thirteen": 13, "thirteenth": 13, "fourteen": 14, "fourteenth": 14, "fifteen": 15, "fifteenth": 15,
    "sixteen": 16, "sixteenth": 16, "seventeen": 17, "seventeenth": 17, "eighteen": 18, "eighteenth": 18,
    "nineteen": 19, "nineteenth": 19, "twenty": 20, "twentieth": 20,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
        "ninety": 90, "twentieth": 20, "thirtieth": 30}
# ponytail: a fixed keyword list can't cover every way a person expresses uncertainty in free-form speech;
# this is a heuristic floor, not complete coverage. Raise it by adding phrases seen missed in real sessions.
# Note: these are matched against fold()'d text, which replaces punctuation (incl. apostrophes) with spaces,
# so entries use the post-fold spelling ("i m not sure", not "i'm not sure").
HEDGES = ["i think", "i guess", "maybe", "probably", "around", "about", "roughly", "approximately", "not sure",
          "i m not sure", "i am not sure", "i don t remember exactly", "sort of",
          "kind of", "something like", "i believe", "it might have been", "could have been", "um", "uh",
          "like maybe", "i don t recall exactly", "if i remember correctly", "if i m not mistaken"]
YES = ["yes", "yeah", "yep", "yup", "correct", "that s right", "thats right", "right", "sure", "affirmative",
       "ok", "okay", "of course", "exactly", "indeed", "certainly"]
NO = ["no", "nope", "never", "none", "negative", "not at all"]
UNSURE = ["not sure", "i m not sure", "i am not sure", "i don t know", "don t know", "no idea",
          "who knows", "i can t recall"]


def has_hedge(text: str) -> bool:
    f = f" {fold(text)} "
    return any(f" {h} " in f or f.strip().startswith(h + " ") for h in HEDGES)


def yes_no(text: str) -> bool | None:
    f = fold(text)
    if not f:
        return None
    words = f.split()
    if any(u in f for u in UNSURE):
        return None
    first = words[0]
    if first in ("no", "nope", "never", "negative"):
        return False
    for y in YES:
        if f == y or f.startswith(y + " ") or f" {y} " in f" {f} ":
            return True
    if any(w in NO for w in words[:3]):
        return False
    return None


def yes_no_unsure(text: str) -> str | None:
    f = fold(text)
    if any(u in f for u in UNSURE):
        return "not_sure"
    yn = yes_no(text)
    if yn is True:
        return "yes"
    if yn is False:
        return "no"
    return None


ORDINAL_NUM = re.compile(r"^(\d{1,2})(st|nd|rd|th)$")


def number_words(tokens: list[str]) -> tuple[int | None, int]:
    """Parse an English number from the start of tokens. Returns (value, tokens_consumed)."""
    if not tokens:
        return None, 0
    if tokens[0].isdigit():
        return int(tokens[0]), 1
    m = ORDINAL_NUM.match(tokens[0])
    if m:
        return int(m[1]), 1
    i = 0
    total = 0
    found = False
    if i < len(tokens) and tokens[i] in TENS:
        total += TENS[tokens[i]]
        found, i = True, i + 1
        if i < len(tokens) and tokens[i] in UNITS and UNITS[tokens[i]] < 10:
            total += UNITS[tokens[i]]
            i += 1
    elif i < len(tokens) and tokens[i] in UNITS:
        total += UNITS[tokens[i]]
        found, i = True, i + 1
    return (total if found else None), i


def _year_from(tokens: list[str], ref_year: int | None) -> tuple[int | None, int]:
    if not tokens:
        return None, 0
    t = tokens[0]
    if t.isdigit():
        n = int(t)
        if len(t) == 4:
            return n, 1
        if len(t) == 2:
            return (2000 + n if n <= 40 else 1900 + n), 1
        return None, 0
    # "twenty twenty-four" (2024), "nineteen ninety-eight" (1998)
    n1, u1 = number_words(tokens)
    if n1 is not None and u1 and tokens[0] in ("twenty", "nineteen", "eighteen") and len(tokens) > u1:
        n2, u2 = number_words(tokens[u1:])
        if n2 is not None and u2:
            century = {"twenty": 2000, "nineteen": 1900, "eighteen": 1800}[tokens[0]]
            return century + n2, u1 + u2
    if n1 is None:
        return None, 0
    if n1 >= 1900:
        return n1, u1
    if n1 < 100 and u1:
        return (2000 + n1 if n1 <= 40 else 1900 + n1), u1
    return None, 0


def parse_date(text: str, ref: str | None = None, today: date | None = None) -> tuple[str | None, str]:
    """Return (value, precision): 'YYYY-MM-DD' (day) or 'YYYY-MM' (month) or 'YYYY' (year)."""
    today = today or date.today()
    raw = text.strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", raw)
    if m:
        mo, d, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y = 2000 + y if y <= 40 else 1900 + y
        if mo > 12 and d <= 12:
            d, mo = mo, d
        return _safe(y, mo, d)
    f = fold(raw)
    tokens = f.split()
    ref_d = None
    if ref:
        try:
            ref_d = date.fromisoformat(ref[:10]) if len(ref) >= 10 else date.fromisoformat(ref[:7] + "-01")
        except ValueError:
            ref_d = None
    day = month = year = None
    for i, tok in enumerate(tokens):
        if tok in MONTHS:
            month = MONTHS[tok]
            # drop leading/trailing articles so "the third of August" / "August 3rd" both reduce to the
            # day number sitting right next to the month (kept out of the global token list so the
            # separate day-only fallback below can still find a literal "the"/"on" token)
            before = [t for t in tokens[:i] if t not in ("the", "of")]
            after = [t for t in tokens[i + 1:] if t != "of"]
            day = None
            if before:
                start = max(0, len(before) - 2)
                n, used = number_words(before[start:])
                if n is not None and 1 <= n <= 31 and start + used == len(before):
                    day = n
            if day is None and after:
                n, used = number_words(after[:2])
                if n is not None and 1 <= n <= 31:
                    day = n
                    after = after[used:]
            year, _ = _year_from(after, ref_d.year if ref_d else None)
            break
    if month is None:
        for i, tok in enumerate(tokens):
            if tok in ("on", "the") and i + 1 < len(tokens):
                n, used = number_words(tokens[i + 1:])
                if n is not None and 1 <= n <= 31 and ref_d:
                    return _safe(ref_d.year, ref_d.month, n)
        m = re.search(r"\b(19\d{2}|20\d{2})\b", raw)
        if m:
            return m[1], "year"
        n, _ = _year_from([t for t in tokens if t not in ("in", "on", "the", "of")], None)
        if n and n >= 1900:
            return str(n), "year"
        return None, ""
    if year is None:
        if ref_d is not None:
            year = ref_d.year
        else:
            year = today.year if month <= today.month else today.year - 1
    if day is None:
        return f"{year:04d}-{month:02d}", "month"
    return _safe(year, month, day)


def _safe(y: int, mo: int, d: int) -> tuple[str | None, str]:
    try:
        return date(y, mo, d).isoformat(), "day"
    except ValueError:
        return None, ""


def parse_int(text: str) -> int | None:
    f = fold(text)
    if re.search(r"\b(none|zero|no kids|no children)\b", f):
        return 0
    m = re.search(r"\b(\d{1,3})\b", f)
    if m:
        return int(m[1])
    toks = f.split()
    for i in range(len(toks)):
        n, used = number_words(toks[i:])
        if n is not None and used:
            return n
    return None


def digits(text: str) -> str:
    """Digits from typed or spoken digits ('nine three nine zero one' -> '93901')."""
    out = []
    for tok in fold(text).replace("-", " ").split():
        if tok.isdigit():
            out.append(tok)
        elif tok in UNITS and UNITS[tok] < 10:
            out.append(str(UNITS[tok]))
    return "".join(out)


FILLERS = re.compile(r"^(well|so|um+|uh+|like|ok|okay|yeah|right|let's see|lets see)[,\s]+", re.IGNORECASE)
NAME_PREFIX = re.compile(
    r"^(my name is|i'm called|i am called|his name is|her name is|their name is|it's|it is|my husband is called|"
    r"my wife is called|my son is called|my daughter is called|i am|i'm|name is)\s+", re.IGNORECASE)


def clean_free_text(text: str) -> str:
    t = text.strip().strip(".!?").strip()
    for _ in range(3):
        t2 = FILLERS.sub("", t)
        if t2 == t:
            break
        t = t2
    return t.strip().strip(",.").strip()


def parse_name(text: str) -> str | None:
    t = clean_free_text(text)
    t = re.sub(r"(…|\.\.\.).*$", "", t)
    t = re.split(r"[,;]| but | well ", t)[0]
    for _ in range(2):
        t = NAME_PREFIX.sub("", t)
    t = t.strip(" .")
    if not t or len(t) > 80:
        return None
    return " ".join(w if w.lower() in ("de", "del", "la", "los", "van", "von") else w[:1].upper() + w[1:]
                    for w in t.split())


COUNTRIES = {
    "mexico": "Mexico", "guatemala": "Guatemala", "el salvador": "El Salvador", "salvador": "El Salvador",
    "honduras": "Honduras", "nicaragua": "Nicaragua", "colombia": "Colombia", "peru": "Peru", "ecuador": "Ecuador",
    "venezuela": "Venezuela", "cuba": "Cuba", "dominican republic": "Dominican Republic", "canada": "Canada",
    "spain": "Spain", "united states": "United States", "costa rica": "Costa Rica", "panama": "Panama",
    "argentina": "Argentina", "chile": "Chile", "bolivia": "Bolivia", "india": "India", "france": "France",
    "japan": "Japan", "china": "China", "philippines": "Philippines", "vietnam": "Vietnam", "haiti": "Haiti",
    "brazil": "Brazil", "nigeria": "Nigeria", "ethiopia": "Ethiopia", "ukraine": "Ukraine", "russia": "Russia",
}


def parse_country(text: str) -> str | None:
    f = fold(text)
    for k in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(k) + r"\b", f):
            return COUNTRIES[k]
    return None


ENUMS: dict[str, list[tuple[str, list[str]]]] = {
    "marital.status": [("married", ["married"]), ("divorced", ["divorced"]), ("widowed", ["widow"]),
                       ("separated", ["separated"]), ("annulled", ["annulled"]), ("single", ["single", "never married"])],
    "spouse.citizenship_status": [("us_citizen", ["citizen", "u.s. citizen", "us citizen"]),
                                  ("lpr", ["permanent resident", "green card", "lpr"]),
                                  ("other", ["other", "none", "no papers"])],
    "fee.method": [("online", ["online", "internet", "computer", "on my account"]),
                   ("paper", ["paper", "mail", "print"])],
    "relationship": [("adopted", ["adopt"]), ("stepchild", ["stepchild", "stepson", "stepdaughter"]),
                     ("biological", ["biological", "my own", "natural", "yes"])],
}


def parse_enum(key: str, text: str) -> str | None:
    f = fold(text)
    for value, stems in ENUMS.get(key, []):
        if any(st in f for st in stems):
            return value
    return None


STATE_WORDS = {"california": "CA", "texas": "TX", "arizona": "AZ", "nevada": "NV", "oregon": "OR",
               "washington": "WA", "new york": "NY", "florida": "FL", "illinois": "IL", "colorado": "CO",
               "new mexico": "NM", "georgia": "GA", "north carolina": "NC", "utah": "UT"}


def parse_state(text: str) -> str | None:
    f = fold(text)
    for k, v in STATE_WORDS.items():
        if k in f:
            return v
    m = re.search(r"\b([A-Za-z]{2})\b", text.strip())
    if m and m[1].upper() in {"CA", "TX", "AZ", "NV", "OR", "WA", "NY", "FL", "IL", "CO", "NM", "GA", "NC", "UT"}:
        return m[1].upper()
    return None


def parse_benefit(text: str) -> str | None | bool:
    f = fold(text)
    for b in ("medi-cal", "medi cal", "medicaid", "calfresh", "snap", "food stamps", "tanf", "calworks", "ssi"):
        if b in f:
            return {"medi cal": "medi-cal", "food stamps": "snap"}.get(b, b)
    if yes_no(text) is False:
        return None
    return False  # not understood


TRIP_REASON = re.compile(r"\b(?:to|for)\s+((?:care for|see|visit|attend|accompany|work|"
                         r"a wedding|a funeral|vacation|business)[^.,;…]*)")


def _soft(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def parse_trip_reason(text: str) -> str | None:
    f = _soft(text)
    m = TRIP_REASON.search(f)
    if m:
        r = m[1].strip()
        r = re.sub(r"\bmy mom\b", "her mother", r)
        r = re.sub(r"\bmy dad\b", "her father", r)
        return r[:120]
    return None


ADVICE_Q = re.compile(r"(do i qualify|will i qualify|will i get approved|will i pass|does that matter|"
                      r"what do you recommend|should i|is it bad|does it affect|i have a problem|"
                      r"will they deny me|can i become a citizen)")


def is_advice_question(text: str) -> bool:
    return bool(ADVICE_Q.search(fold(text)))


def wants_to_stop(text: str) -> bool:
    f = fold(text)
    return bool(re.search(r"\b(finish|let s stop|another day|i don t want to anymore|better later|hang up|"
                          r"goodbye|bye|see you tomorrow|i have to go)\b", f))


def third_party_relation(text: str) -> str | None:
    f = fold(text)
    for w, rel in (("daughter", "daughter"), ("son", "son"), ("husband", "husband"), ("wife", "wife"),
                   ("granddaughter", "granddaughter"), ("grandson", "grandson"), ("sister", "sister"),
                   ("brother", "brother"), ("friend", "friend"), ("niece", "niece"), ("nephew", "nephew")):
        if re.search(r"\b" + w + r"\b", f):
            return rel
    return None


def strip_yes_no(text: str) -> str:
    """Drop a leading yes/no ("No, the 13th!" -> "the 13th!")."""
    t = text.strip()
    t = re.sub(r"(?i)^(yes|yeah|yep|yup|no|nope|correct|right|that.?s right|sure|exactly|ok)\b[\s,.!:;-]*", "", t)
    return t.strip()


def parse_value(key: str, ftype: str, text: str, ref: str | None = None,
                today: date | None = None) -> tuple[Any, bool]:
    """Parse an answer for a field. Returns (value, understood)."""
    if ftype in ("date", "date_or_present"):
        if ftype == "date_or_present" and re.search(r"\b(now|present|still|currently|to this day|to date)\b", fold(text)):
            return "present", True
        v, _ = parse_date(text, ref=ref, today=today)
        return v, v is not None
    if ftype == "bool":
        v = yes_no(text)
        return v, v is not None
    if ftype == "yes_no_unsure":
        v = yes_no_unsure(text)
        if v is None and len(fold(text).split()) >= 3:
            return "yes", True
        return v, v is not None
    if ftype == "int":
        v = parse_int(text)
        return v, v is not None
    if ftype == "country":
        v = parse_country(text)
        return v, v is not None
    if ftype in ("name",):
        if yes_no(text) is not None and len(fold(text).split()) <= 2:
            return None, False
        v = parse_name(text)
        return v, v is not None
    if ftype == "optional_name":
        f = fold(text)
        if yes_no(text) is False:
            return None, True
        name = parse_name(re.sub(r"^(yes|sure)[,:\s]+", "", f, flags=re.I)) if ":" not in text else parse_name(
            text.split(":", 1)[1])
        if name and fold(name) not in ("yes", "sure", "yes i want to"):
            return parse_name(text.split(":", 1)[1] if ":" in text else re.sub(r"(?i)^\s*yes[,\s]+", "", text)), True
        return "__YES__", True
    if ftype == "string_list":
        if yes_no(text) is False or re.search(r"\b(none|no other|nothing)\b", fold(text)):
            return [], True
        t = clean_free_text(text)
        t = re.sub(r"(?i)^(yes[,\s]+)", "", t)
        parts = [parse_name(p) for p in re.split(r",| and ", t) if p.strip()]
        parts = [p for p in parts if p]
        return parts, bool(parts)
    if ftype == "enum":
        v = parse_enum(key.split("].")[-1] if "]." in key else key, text)
        return v, v is not None
    if ftype == "us_state":
        v = parse_state(text)
        return v, v is not None
    if ftype == "zip":
        d = digits(text)
        return (d, True) if len(d) == 5 else (None, False)
    if ftype == "benefit":
        v = parse_benefit(text)
        return (None, False) if v is False else (v, True)
    if (yes_no(text) is not None and len(fold(text).split()) <= 2) or yes_no_unsure(text) == "not_sure":
        return None, False
    t = clean_free_text(text)
    t = re.sub(r"(?i)^(i live in|i lived in|i work at|i worked at|in|i am|i was|i went to)\s+", "", t)
    return (t[:200], True) if t else (None, False)
