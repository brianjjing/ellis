"""Validate and normalize fact values against the catalog type (record_fact step 2)."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .catalog import DEFERRED, field_def

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC", "PR",
}
STATE_NAMES = {"california": "CA", "texas": "TX", "arizona": "AZ", "nevada": "NV", "oregon": "OR", "washington": "WA",
               "nueva york": "NY", "new york": "NY", "florida": "FL", "illinois": "IL", "colorado": "CO",
               "nuevo mexico": "NM", "new mexico": "NM", "georgia": "GA", "carolina del norte": "NC"}


class ValueError_(ValueError):
    pass


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "yes", "si", "sí", "1"):
        return True
    if s in ("false", "no", "0"):
        return False
    raise ValueError_("expected yes/no")


def _date(v: Any, allow_partial: bool = True) -> str:
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        date.fromisoformat(s)
        return s
    if allow_partial and re.fullmatch(r"\d{4}-\d{2}", s):
        date.fromisoformat(s + "-01")
        return s
    if allow_partial and re.fullmatch(r"\d{4}", s):
        return s
    raise ValueError_("expected an ISO date (YYYY-MM-DD)")


def normalize(key: str, value: Any) -> Any:
    d = field_def(key)
    if d is None:
        raise ValueError_(f"unknown field {key}")
    if value == DEFERRED:
        return DEFERRED
    t = d.get("type", "string")
    if t == "bool":
        return _bool(value)
    if t == "date":
        return _date(value)
    if t == "date_or_present":
        if str(value).lower() in ("present", "presente", "actual"):
            return "present"
        return _date(value)
    if t == "int":
        try:
            return int(str(value).strip())
        except ValueError:
            raise ValueError_("expected a whole number") from None
    if t == "enum":
        s = str(value).strip().lower()
        if s not in d.get("options", []):
            raise ValueError_(f"expected one of {d.get('options')}")
        return s
    if t == "yes_no_unsure":
        s = str(value).strip().lower()
        s = {"si": "yes", "sí": "yes", "true": "yes", "false": "no", "unsure": "not_sure", "no se": "not_sure"}.get(s, s)
        if s not in ("yes", "no", "not_sure"):
            raise ValueError_("expected yes / no / not_sure")
        return s
    if t == "string_list":
        if value in (None, "", "none", "ninguno"):
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return [x.strip() for x in str(value).split(",") if x.strip()]
    if t == "optional_name":
        if value in (None, "", "none", "no"):
            return None
        return str(value).strip()
    if t == "a_number":
        s = re.sub(r"[\s\-]", "", str(value)).upper()
        if not s.startswith("A"):
            s = "A" + s
        if not re.fullmatch(r"A\d{8,9}", s):
            raise ValueError_("A-number is A followed by 8 or 9 digits")
        return s
    if t == "ssn":
        s = re.sub(r"\D", "", str(value))
        if len(s) != 9:
            raise ValueError_("SSN has 9 digits")
        return f"{s[:3]}-{s[3:5]}-{s[5:]}"
    if t == "uscis_account":
        s = re.sub(r"\D", "", str(value))
        if len(s) != 12:
            raise ValueError_("USCIS online account number has 12 digits")
        return s
    if t == "phone":
        s = re.sub(r"\D", "", str(value))
        if len(s) == 11 and s.startswith("1"):
            s = s[1:]
        if len(s) != 10:
            raise ValueError_("phone has 10 digits")
        return f"({s[:3]}) {s[3:6]}-{s[6:]}"
    if t == "email":
        s = str(value).strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
            raise ValueError_("invalid email")
        return s
    if t == "zip":
        s = re.sub(r"\D", "", str(value))
        if len(s) != 5:
            raise ValueError_("ZIP has 5 digits")
        return s
    if t == "us_state":
        s = str(value).strip()
        if s.upper() in US_STATES:
            return s.upper()
        from .keywords import fold
        f = fold(s)
        if f in STATE_NAMES:
            return STATE_NAMES[f]
        raise ValueError_("unknown US state")
    if t == "benefit":
        s = str(value).strip().lower()
        return None if s in ("", "none", "no", "ninguno") else s
    s = str(value).strip()
    if not s:
        raise ValueError_("empty value")
    return s


def display_value(key: str, value: Any) -> str:
    """Short human display (English/neutral) used in clinic UI and PDFs."""
    if value is None:
        return "—"
    if value == DEFERRED:
        return "Deferred to licensed professional"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(value) if value else "None"
    return str(value)


def equal(key: str, a: Any, b: Any) -> bool:
    """Value equality for conflict checks: names, countries and free text compare accent- and case-insensitively."""
    if a == b:
        return True
    d = field_def(key) or {}
    if d.get("type") in ("name", "optional_name", "country", "string") and isinstance(a, str) and isinstance(b, str):
        from .keywords import fold
        fa, fb = fold(a), fold(b)
        if d.get("type") == "country":
            alias = {"mexico": "mexico", "mexicana": "mexico", "mexicano": "mexico", "mex": "mexico"}
            fa, fb = alias.get(fa, fa), alias.get(fb, fb)
        return fa == fb
    return False
