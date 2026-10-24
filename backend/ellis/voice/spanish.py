"""Spanish answer parsing for the liaison: dates, yes/no, hedges, numbers, names, enums.

The liaison only parses what the applicant said into a canonical value; it never computes with dates.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..services.keywords import fold

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
UNITS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "primero": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
}
TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
        "noventa": 90}
HEDGES = ["creo", "mas o menos", "no me acuerdo bien", "no recuerdo bien", "como en", "como el", "aproximadamente",
          "tal vez", "quizas", "a lo mejor", "por ahi", "mas bien", "no estoy segur", "eh", "este", "i think",
          "maybe", "como por", "como a", "algo asi", "como que"]
YES = ["si", "sip", "claro", "correcto", "asi es", "de acuerdo", "esta bien", "afirmativo", "yes", "eso es", "exacto",
       "ok", "okay", "vale", "por supuesto", "cierto", "andale", "sale", "simon", "bueno si", "dale"]
NO = ["no", "nunca", "negativo", "ninguno", "ninguna", "jamas", "nope", "nada"]
UNSURE = ["no se", "no estoy segur", "no me acuerdo", "no recuerdo", "quien sabe", "not sure", "no lo se"]


def has_hedge(text: str) -> bool:
    f = f" {fold(text)} "
    return any(f" {h} " in f or f.strip().startswith(h + " ") for h in HEDGES)


def yes_no(text: str) -> bool | None:
    f = fold(text)
    if not f:
        return None
    words = f.split()
    if any(f.startswith(u) or f" {u}" in f" {f}" for u in UNSURE):
        return None
    first = words[0]
    if first in ("no", "nunca", "negativo", "jamas", "nope"):
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


def number_words(tokens: list[str]) -> tuple[int | None, int]:
    """Parse a Spanish number from the start of tokens. Returns (value, tokens_consumed)."""
    i = 0
    total = 0
    found = False
    if i < len(tokens) and tokens[i].isdigit():
        return int(tokens[i]), 1
    if i < len(tokens) and tokens[i] == "mil":
        total, found, i = 1000, True, i + 1
    elif i + 1 < len(tokens) and tokens[i] in UNITS and tokens[i + 1] == "mil":
        total, found, i = UNITS[tokens[i]] * 1000, True, i + 2
    if i < len(tokens) and tokens[i] in ("novecientos", "ochocientos"):
        total += {"novecientos": 900, "ochocientos": 800}[tokens[i]]
        found, i = True, i + 1
    if i < len(tokens) and tokens[i] in TENS:
        total += TENS[tokens[i]]
        found, i = True, i + 1
        if i + 1 < len(tokens) and tokens[i] == "y" and tokens[i + 1] in UNITS and UNITS[tokens[i + 1]] < 10:
            total += UNITS[tokens[i + 1]]
            i += 2
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
    n, used = number_words(tokens)
    if n is None:
        return None, 0
    if n >= 1900:
        return n, used
    if n < 100 and used:
        # "del veinticuatro" → 2024, "del noventa y ocho" → 1998
        return (2000 + n if n <= 40 else 1900 + n), used
    return None, 0


def parse_date(text: str, ref: str | None = None, today: date | None = None) -> tuple[str | None, str]:
    """Return (value, precision): 'YYYY-MM-DD' (day) or 'YYYY-MM' (month) or 'YYYY' (year).

    `ref` (ISO) fills in a missing month/year, e.g. a barge-in "¡el trece!" during a read-back of 2024-03-03.
    """
    today = today or date.today()
    raw = text.strip()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if m:
        return _safe(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", raw)
    if m:
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y = 2000 + y if y <= 40 else 1900 + y
        if mo > 12 and d <= 12:  # US order typed by mistake
            d, mo = mo, d
        return _safe(y, mo, d)
    f = fold(raw)
    f = re.sub(r"\bdel\b", "de", f)
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
            # day before the month: "tres de agosto", "el 3 de agosto"
            j = i - 1
            if j >= 0 and tokens[j] == "de":
                j -= 1
            if j >= 0:
                k = j
                while k > 0 and tokens[k - 1] in TENS.keys() | {"y"}:
                    k -= 1
                n, used = number_words(tokens[k:j + 1])
                if n is not None and 1 <= n <= 31 and k + used == j + 1:
                    day = n
            # year after the month: "de 2023", "del veinticuatro", "de dos mil veintidos"
            rest = tokens[i + 1:]
            while rest and rest[0] in ("de", "del", "en", "el", "ano", "a"):
                rest = rest[1:]
            year, _ = _year_from(rest, ref_d.year if ref_d else None)
            break
    if month is None:
        # "el trece" (day only) or "en 2019" (year only)
        for i, tok in enumerate(tokens):
            if tok in ("el", "dia") and i + 1 < len(tokens):
                n, used = number_words(tokens[i + 1:])
                if n is not None and 1 <= n <= 31 and ref_d:
                    return _safe(ref_d.year, ref_d.month, n)
        m = re.search(r"\b(19\d{2}|20\d{2})\b", raw)
        if m:
            return m[1], "year"
        n, _ = _year_from([t for t in tokens if t not in ("en", "el", "ano", "de")], None)
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
    if re.search(r"\b(ninguno|ninguna|no tengo|cero|ningun)\b", f):
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
    """Digits from typed or spoken digits ('nueve tres nueve cero uno' → '93901')."""
    out = []
    for tok in fold(text).replace("-", " ").split():
        if tok.isdigit():
            out.append(tok)
        elif tok in UNITS and UNITS[tok] < 10:
            out.append(str(UNITS[tok]))
    return "".join(out)


FILLERS = re.compile(
    r"^(bueno|pues|este|eh+|mm+|ah|ok|okay|si|claro|mire|fijese|ah si)[,\s]+", re.IGNORECASE)
NAME_PREFIX = re.compile(
    r"^(me llamo|mi nombre es|se llama|mi esposo se llama|mi esposa se llama|mi hijo se llama|mi hija se llama|"
    r"su nombre es|soy|es|el nombre es|el|ella|ella es|el es|nombre)\s+", re.IGNORECASE)


def clean_free_text(text: str) -> str:
    t = text.strip().strip(".!¡¿?").strip()
    for _ in range(3):
        t2 = FILLERS.sub("", t)
        if t2 == t:
            break
        t = t2
    return t.strip().strip(",.").strip()


def parse_name(text: str) -> str | None:
    t = clean_free_text(text)
    t = re.sub(r"(…|\.\.\.).*$", "", t)
    t = re.split(r"[,;]| pero | bueno ", t)[0]
    for _ in range(2):
        t = NAME_PREFIX.sub("", t)
    t = t.strip(" .")
    if not t or len(t) > 80:
        return None
    return " ".join(w if w.lower() in ("de", "del", "la", "los", "y") else w[:1].upper() + w[1:] for w in t.split())


COUNTRIES = {
    "mexico": "Mexico", "mexicana": "Mexico", "mexicano": "Mexico", "guatemala": "Guatemala",
    "guatemalteca": "Guatemala", "guatemalteco": "Guatemala", "el salvador": "El Salvador", "salvadorena": "El Salvador",
    "salvadoreno": "El Salvador", "honduras": "Honduras", "hondurena": "Honduras", "hondureno": "Honduras",
    "nicaragua": "Nicaragua", "colombia": "Colombia", "colombiana": "Colombia", "colombiano": "Colombia",
    "peru": "Peru", "ecuador": "Ecuador", "venezuela": "Venezuela", "cuba": "Cuba", "republica dominicana":
        "Dominican Republic", "canada": "Canada", "espana": "Spain", "estados unidos": "United States",
    "costa rica": "Costa Rica", "panama": "Panama", "argentina": "Argentina", "chile": "Chile", "bolivia": "Bolivia",
}


def parse_country(text: str) -> str | None:
    f = fold(text)
    for k in sorted(COUNTRIES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(k) + r"\b", f):
            return COUNTRIES[k]
    return None


ENUMS: dict[str, list[tuple[str, list[str]]]] = {
    "marital.status": [("married", ["casad", "married"]), ("divorced", ["divorciad"]), ("widowed", ["viud"]),
                       ("separated", ["separad"]), ("annulled", ["anulad"]), ("single", ["solter", "single"])],
    "spouse.citizenship_status": [("us_citizen", ["ciudadan"]), ("lpr", ["residente", "green card", "mica"]),
                                  ("other", ["otro", "otra", "ninguno", "sin papeles"])],
    "fee.method": [("online", ["linea", "internet", "online", "computadora", "en la cuenta"]),
                   ("paper", ["papel", "correo", "imprimir", "mail"])],
    "relationship": [("adopted", ["adoptad"]), ("stepchild", ["hijastr", "entenad"]),
                     ("biological", ["biologic", "mi hij", "propi", "natural", "si"])],
}


def parse_enum(key: str, text: str) -> str | None:
    f = fold(text)
    for value, stems in ENUMS.get(key, []):
        if any(st in f for st in stems):
            return value
    return None


STATE_WORDS = {"california": "CA", "texas": "TX", "arizona": "AZ", "nevada": "NV", "oregon": "OR",
               "washington": "WA", "nueva york": "NY", "new york": "NY", "florida": "FL", "illinois": "IL",
               "colorado": "CO", "nuevo mexico": "NM", "georgia": "GA", "carolina del norte": "NC", "utah": "UT"}


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
    for b in ("medi cal", "medical", "medicaid", "calfresh", "snap", "estampillas", "tanf", "calworks", "ssi"):
        if b in f:
            return {"medi cal": "medi-cal", "medical": "medi-cal", "estampillas": "snap"}.get(b, b)
    if yes_no(text) is False:
        return None
    return False  # not understood


TRIP_REASON = re.compile(r"\b(?:a|para|por)\s+((?:cuidar|ver|visitar|atender|acompanar|trabajar|"
                         r"la boda|el funeral|vacaciones|negocios)[^.,;…]*)")


def _soft(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def parse_trip_reason(text: str) -> str | None:
    f = _soft(text)
    m = TRIP_REASON.search(f)
    if m:
        r = m[1].strip()
        r = re.sub(r"\bmi mama\b", "su madre", r)
        r = re.sub(r"\bmi papa\b", "su padre", r)
        return r[:120]
    return None


ADVICE_Q = re.compile(r"(califico|me van a aprobar|me aprueban|voy a pasar|eso importa|importa eso|que me recomienda|"
                      r"debo |deberia|me conviene|tengo problema|es malo|me afecta|puedo ser ciudadan|"
                      r"me van a negar|me niegan|will i|should i|do i qualify)")


def is_advice_question(text: str) -> bool:
    return bool(ADVICE_Q.search(fold(text)))


def wants_to_stop(text: str) -> bool:
    f = fold(text)
    return bool(re.search(r"\b(terminar|terminemos|otro dia|ya no quiero|mejor despues|colgar|adios|hasta luego|"
                          r"seguimos manana|ya me tengo que ir)\b", f))


def third_party_relation(text: str) -> str | None:
    f = fold(text)
    for w, rel in (("hija", "daughter"), ("hijo", "son"), ("esposo", "husband"), ("esposa", "wife"),
                   ("nieta", "granddaughter"), ("nieto", "grandson"), ("hermana", "sister"), ("hermano", "brother"),
                   ("amiga", "friend"), ("amigo", "friend"), ("sobrina", "niece"), ("sobrino", "nephew")):
        if re.search(r"\b" + w + r"\b", f):
            return rel
    return None


def parse_value(key: str, ftype: str, text: str, ref: str | None = None,
                today: date | None = None) -> tuple[Any, bool]:
    """Parse an answer for a field. Returns (value, understood)."""
    if ftype in ("date", "date_or_present"):
        if ftype == "date_or_present" and re.search(r"\b(ahora|presente|todavia|actualmente|hasta hoy)\b", fold(text)):
            return "present", True
        v, _ = parse_date(text, ref=ref, today=today)
        return v, v is not None
    if ftype == "bool":
        v = yes_no(text)
        return v, v is not None
    if ftype == "yes_no_unsure":
        v = yes_no_unsure(text)
        if v is None and len(fold(text).split()) >= 3:
            # an answer that describes an event is a "yes" (fail toward review)
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
        name = parse_name(re.sub(r"^(si|claro)[,:\s]+", "", f, flags=re.I)) if ":" not in text else parse_name(
            text.split(":", 1)[1])
        if name and fold(name) not in ("si", "claro", "si quiero"):
            return parse_name(text.split(":", 1)[1] if ":" in text else re.sub(r"(?i)^\s*s[ií][,\s]+", "", text)), True
        return "__YES__", True
    if ftype == "string_list":
        if yes_no(text) is False or re.search(r"\b(ninguno|ningun otro|nada)\b", fold(text)):
            return [], True
        t = clean_free_text(text)
        t = re.sub(r"(?i)^(s[ií][,\s]+)", "", t)
        parts = [parse_name(p) for p in re.split(r",| y ", t) if p.strip()]
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
        return None, False  # a bare "sí"/"no"/"no sé" is not an answer to an open question
    t = clean_free_text(text)
    t = re.sub(r"(?i)^(vivo en|vivia en|trabajo en|trabajaba en|en|soy|era|fui a|fue a)\s+", "", t)
    return (t[:200], True) if t else (None, False)


def strip_yes_no(text: str) -> str:
    """Drop a leading yes/no ("¡No, el trece!" → "el trece!")."""
    t = text.strip().lstrip("¡¿").strip()
    t = re.sub(r"(?i)^(s[ií]|no|claro|correcto|así es|asi es|exacto|ok)\b[\s,.!¡:;-]*", "", t)
    return t.strip()
