"""Ellis rules engine.

Pure functions: no I/O, no model calls. The only code allowed to compute dates, day counts,
exemptions or fees. Every output carries a rule_id, the rule_config_version and a Spanish
explain string the liaison may read verbatim. Rules marked NEEDS EXPERT CHECK must be verified
by a qualified person before any real use.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


class ValidationError(ValueError):
    """Raised (never silently fixed) when inputs are impossible. `field` names the offending fact."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


@dataclass(frozen=True)
class Trip:
    departure: date
    return_: date | None = None
    index: int = 0


@dataclass
class RuleConfig:
    version: str
    trip_day_convention: str = "calendar_difference"
    years_lpr: int = 5
    physical_presence_days: int = 913
    early_filing_days: int = 90
    district_months: int = 3
    rebuttable_days_gt: int = 180
    breaks_days_gte: int = 365
    exemptions: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "e50_20": {"min_age": 50, "min_lpr_years": 20},
        "e55_15": {"min_age": 55, "min_lpr_years": 15},
        "e65_20": {"min_age": 65, "min_lpr_years": 20},
    })
    civics_cutoff: date = date(2025, 10, 20)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RuleConfig":
        p = d["paths"]["5yr"]
        cutoff = d["civics"]["cutoff_2025_test"]
        return cls(
            version=str(d["version"]),
            trip_day_convention=d.get("trip_day_convention", "calendar_difference"),
            years_lpr=p["years_lpr"],
            physical_presence_days=p["physical_presence_days"],
            early_filing_days=p["early_filing_days"],
            district_months=p["district_months"],
            rebuttable_days_gt=d["absence"]["rebuttable_days_gt"],
            breaks_days_gte=d["absence"]["breaks_days_gte"],
            exemptions=d["exemptions"],
            civics_cutoff=cutoff if isinstance(cutoff, date) else date.fromisoformat(str(cutoff)),
        )


@dataclass
class FeeConfig:
    version: str
    online: int
    paper: int
    reduced_amount: int
    waiver_form: str
    reduced_form: str
    means_tested: list[str]
    fpg_base: int
    fpg_per_person: int
    fpg_version: str
    watch: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FeeConfig":
        n = d["n400"]
        return cls(
            version=d["version"],
            online=n["online"],
            paper=n["paper"],
            reduced_amount=n["reduced"]["amount"],
            waiver_form=n["waiver"]["form"],
            reduced_form=n["reduced"].get("form", "I-942"),
            means_tested=[b.lower() for b in d.get("means_tested_benefits", [])],
            fpg_base=d["poverty_guidelines"]["base"],
            fpg_per_person=d["poverty_guidelines"]["per_additional_person"],
            fpg_version=d["poverty_guidelines"]["version"],
            watch=d.get("watch", []),
        )


# ---------------------------------------------------------------- spoken forms

NUM_ES = {
    1: "primero", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho",
    9: "nueve", 10: "diez", 11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince",
    16: "dieciséis", 17: "diecisiete", 18: "dieciocho", 19: "diecinueve", 20: "veinte",
    21: "veintiuno", 22: "veintidós", 23: "veintitrés", 24: "veinticuatro", 25: "veinticinco",
    26: "veintiséis", 27: "veintisiete", 28: "veintiocho", 29: "veintinueve", 30: "treinta",
    31: "treinta y uno",
}


def year_es(y: int) -> str:
    """Spanish words for a year in 1900–2099 (e.g. 2024 -> 'dos mil veinticuatro')."""
    if y >= 2000:
        rest = y - 2000
        return "dos mil" if rest == 0 else f"dos mil {_under_100_es(rest)}"
    rest = y - 1900
    return "mil novecientos" if rest == 0 else f"mil novecientos {_under_100_es(rest)}"


def _under_100_es(n: int) -> str:
    if n <= 31:
        return "uno" if n == 1 else NUM_ES[n]
    tens = {3: "treinta", 4: "cuarenta", 5: "cincuenta", 6: "sesenta", 7: "setenta", 8: "ochenta", 9: "noventa"}
    t, u = divmod(n, 10)
    return tens[t] if u == 0 else f"{tens[t]} y {'uno' if u == 1 else NUM_ES[u]}"


def spoken_date_es(d: date) -> str:
    """Canonical spoken form: 'el quince de enero de dos mil veintidós'."""
    day = "primero" if d.day == 1 else NUM_ES[d.day]
    return f"el {day} de {MONTHS_ES[d.month - 1]} de {year_es(d.year)}"


def short_date_es(d: date) -> str:
    return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"


# ---------------------------------------------------------------- date helpers

def add_years(d: date, years: int) -> date:
    """Calendar anniversary; Feb 29 maps to Feb 28 in non-leap years."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def years_between(start: date, end: date) -> int:
    """Whole years from start to end (age-style)."""
    y = end.year - start.year
    if (end.month, end.day) < (start.month, start.day):
        y -= 1
    return y


# ---------------------------------------------------------------- rules

def trip_days(departure: date, return_: date, cfg: RuleConfig) -> int:
    """Days outside the US for one trip. NEEDS EXPERT CHECK on the convention (open question 2)."""
    diff = (return_ - departure).days
    if cfg.trip_day_convention == "exclude_travel_days":
        return max(diff - 1, 0)
    return diff


def statutory_window(filing_date: date, lpr_since: date, cfg: RuleConfig) -> tuple[date, date]:
    """(start, end): start = later of lpr_since and filing date minus N years; end = filing date."""
    back = add_years(filing_date, -cfg.years_lpr)
    return (max(lpr_since, back), filing_date)


def days_abroad(trips: list[Trip], window: tuple[date, date], cfg: RuleConfig) -> tuple[int, list[str]]:
    """Days abroad clipped to the window. An open trip counts through window end (R-TRIP-OPEN)."""
    start, end = window
    total = 0
    rules: list[str] = []
    for t in trips:
        ret = t.return_
        if ret is None:
            rules.append("R-TRIP-OPEN")
            ret = end
        lo = max(t.departure, start)
        hi = min(ret, end)
        if hi <= lo:
            continue
        if lo == t.departure and hi == ret:
            total += trip_days(lo, hi, cfg)
        else:
            total += (hi - lo).days
    return total, rules


def physical_presence(window: tuple[date, date], trips: list[Trip], cfg: RuleConfig) -> dict[str, Any]:
    window_days = (window[1] - window[0]).days
    abroad, rules = days_abroad(trips, window, cfg)
    presence = window_days - abroad
    ok = presence >= cfg.physical_presence_days
    rules.append("R-PP-913")
    return {
        "window_start": window[0].isoformat(),
        "window_end": window[1].isoformat(),
        "window_days": window_days,
        "days_abroad": abroad,
        "presence_days": presence,
        "required_days": cfg.physical_presence_days,
        "meets_presence": ok,
        "rules": rules,
    }


def anniversary(lpr_since: date, years: int) -> date:
    return add_years(lpr_since, years)


def earliest_filing(lpr_since: date, cfg: RuleConfig) -> date:
    """Anniversary minus early-filing days (R-ELIG-EARLY)."""
    return anniversary(lpr_since, cfg.years_lpr) - timedelta(days=cfg.early_filing_days)


def absence_flags(trips: list[Trip], cfg: RuleConfig, as_of: date | None = None) -> list[dict[str, Any]]:
    """R-ABS-180 for any trip > 180 and < 365 days; R-ABS-365 for >= 365."""
    out = []
    for t in trips:
        ret = t.return_ or as_of
        if ret is None:
            continue
        days = trip_days(t.departure, ret, cfg)
        if days >= cfg.breaks_days_gte:
            out.append({"rule_id": "R-ABS-365", "category": "absence_gte_365", "trip_index": t.index, "days": days})
        elif days > cfg.rebuttable_days_gt:
            out.append({"rule_id": "R-ABS-180", "category": "absence_gt_180", "trip_index": t.index, "days": days})
    return out


def residence_district(current_address_from: date | None, filing_date: date, cfg: RuleConfig) -> dict[str, Any] | None:
    """R-RES-3M if the current address began less than N months before filing."""
    if current_address_from is None:
        return None
    m = filing_date.month - cfg.district_months
    y = filing_date.year
    while m <= 0:
        m += 12
        y -= 1
    try:
        cutoff = filing_date.replace(year=y, month=m)
    except ValueError:
        cutoff = date(y, m, 28)
    if current_address_from > cutoff:
        return {"rule_id": "R-RES-3M", "category": "residence_short", "address_from": current_address_from.isoformat()}
    return None


def exemptions(dob: date, lpr_since: date, filing_date: date, cfg: RuleConfig) -> dict[str, bool]:
    """{e50_20, e55_15, e65_20} at the filing date (age and LPR years both measured at filing)."""
    age = years_between(dob, filing_date)
    lpr_years = years_between(lpr_since, filing_date)
    return {
        k: age >= v["min_age"] and lpr_years >= v["min_lpr_years"]
        for k, v in sorted(cfg.exemptions.items())
    }


def civics_version(filing_date: date, cfg: RuleConfig) -> str:
    return "2025-128" if filing_date >= cfg.civics_cutoff else "2008-100"


def fpg_limit(household_size: int, fees: FeeConfig) -> int:
    return fees.fpg_base + fees.fpg_per_person * max(household_size - 1, 0)


def fee(method: str, benefit_type: str | None, household_size: int | None, income: int | None,
        as_of: date, fees: FeeConfig) -> dict[str, Any]:
    """N-400 fee. Waiver and reduced fee are paper-only. NEEDS EXPERT CHECK on waiver criteria (open question 9)."""
    if method not in ("online", "paper"):
        raise ValidationError("fee.method", f"unknown filing method {method!r}")
    base = {"fee_table_version": fees.version, "as_of": as_of.isoformat(),
            "watch": [w["text"] for w in fees.watch], "rule_id": "R-FEE"}
    benefit = (benefit_type or "").strip().lower() or None
    waiver_basis = None
    if benefit and benefit in fees.means_tested:
        waiver_basis = "means_tested_benefit"
    elif household_size and income is not None and income <= fpg_limit(household_size, fees) * 1.5:
        waiver_basis = "income_150_fpg"
    reduced_ok = (
        household_size is not None and income is not None
        and income <= fpg_limit(household_size, fees) * 4
    )
    if waiver_basis:
        option = {"amount": 0, "form": fees.waiver_form, "paper_only": True, "basis": waiver_basis,
                  "fallback": {"amount": fees.reduced_amount, "form": fees.reduced_form, "paper_only": True} if reduced_ok
                  else {"amount": fees.paper, "form": None, "paper_only": False}}
        if method == "online":
            return {**base, "error": "waiver_requires_paper", "amount": fees.online, "form": None,
                    "paper_only": False, "paper_option": option,
                    "explain_es": "La exención de pago solo se puede pedir en papel. En línea la tarifa es de "
                                  f"{fees.online} dólares."}
        return {**base, **option, "waiver_candidate": True,
                "explain_es": "Según la tabla de tarifas, puede pedir la exención de pago con el formulario I-912, en papel."}
    if reduced_ok:
        option = {"amount": fees.reduced_amount, "form": fees.reduced_form, "paper_only": True, "basis": "income_400_fpg"}
        if method == "online":
            return {**base, "amount": fees.online, "form": None, "paper_only": False, "paper_option": option,
                    "explain_es": f"La tarifa en línea es de {fees.online} dólares. La tarifa reducida solo existe en papel."}
        return {**base, **option,
                "explain_es": f"Según la tabla de tarifas, la tarifa reducida en papel es de {fees.reduced_amount} dólares."}
    amount = fees.online if method == "online" else fees.paper
    return {**base, "amount": amount, "form": None, "paper_only": method == "paper",
            "explain_es": f"La tarifa {'en línea' if method == 'online' else 'en papel'} es de {amount} dólares."}


# ---------------------------------------------------------------- validation

def validate(trips: list[Trip], lpr_since: date | None, dob: date | None, as_of: date) -> None:
    for t in trips:
        if t.departure > as_of:
            raise ValidationError(f"trips[{t.index}].departure", "date is in the future")
        if t.return_ is not None:
            if t.return_ < t.departure:
                raise ValidationError(f"trips[{t.index}].return", "return is before departure")
            if t.return_ > as_of:
                raise ValidationError(f"trips[{t.index}].return", "date is in the future")
    closed = sorted(trips, key=lambda t: t.departure)
    for a, b in zip(closed, closed[1:]):
        a_end = a.return_ or as_of
        if b.departure < a_end:
            raise ValidationError(f"trips[{b.index}].departure", f"overlaps trip {a.index}")
    if lpr_since is not None:
        if lpr_since > as_of:
            raise ValidationError("lpr_since", "date is in the future")
        if dob is not None and (lpr_since < dob or lpr_since > add_years(dob, 120)):
            raise ValidationError("lpr_since", "inconsistent with date of birth")
    if dob is not None and dob > as_of:
        raise ValidationError("dob", "date is in the future")


# ---------------------------------------------------------------- evaluate

def _d(v: Any) -> date | None:
    """Parse a fact value into a date. Month-precision 'YYYY-MM' maps to the 1st (low confidence)."""
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    s = str(v)
    if len(s) == 7:
        return date.fromisoformat(s + "-01")
    if len(s) == 4:
        return date.fromisoformat(s + "-01-01")
    return date.fromisoformat(s[:10])


def trips_from_facts(facts: dict[str, Any]) -> list[Trip]:
    idx = sorted({int(k.split("[")[1].split("]")[0]) for k in facts if k.startswith("trips[")})
    out = []
    for i in idx:
        dep = _d(facts.get(f"trips[{i}].departure"))
        if dep is None:
            continue
        out.append(Trip(departure=dep, return_=_d(facts.get(f"trips[{i}].return")), index=i))
    return out


def inputs_hash(facts: dict[str, Any], as_of: date, cfg_version: str) -> str:
    blob = json.dumps({"facts": facts, "as_of": as_of.isoformat(), "cfg": cfg_version}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def evaluate(facts: dict[str, Any], as_of: date, cfg: RuleConfig, fees: FeeConfig | None = None,
             low_confidence_fields: set[str] | None = None) -> dict[str, Any]:
    """One derived record from current facts {field: value}. Deterministic for identical inputs."""
    low_conf = sorted(low_confidence_fields or set())
    out: dict[str, Any] = {
        "as_of": as_of.isoformat(),
        "rule_config_version": cfg.version,
        "inputs_hash": inputs_hash({**facts, "_low": low_conf}, as_of, cfg.version),
        "flags": [],
        "explain": {},
        "error": None,
        "low_confidence": bool(low_conf),
    }
    trips = trips_from_facts(facts)
    lpr = _d(facts.get("lpr_since"))
    dob = _d(facts.get("dob"))
    try:
        validate(trips, lpr, dob, as_of)
    except ValidationError as e:
        out["error"] = {"code": "validation", "field": e.field, "message": e.message}
        return out

    filing = _d(facts.get("filing.planned_date")) or as_of
    out["filing_date"] = filing.isoformat()
    out["trips"] = []
    for t in trips:
        if t.return_ is not None:
            out["trips"].append({"index": t.index, "days": trip_days(t.departure, t.return_, cfg), "open": False})
        else:
            out["trips"].append({"index": t.index, "days": (as_of - t.departure).days, "open": True})
    if out["trips"]:
        out["trip_days"] = out["trips"][0]["days"]
    out["flags"].extend(absence_flags(trips, cfg, as_of))

    if lpr is not None:
        anniv = anniversary(lpr, cfg.years_lpr)
        early = earliest_filing(lpr, cfg)
        out["path"] = "5yr"
        out["anniversary"] = anniv.isoformat()
        out["earliest_filing"] = early.isoformat()
        out["window_open"] = as_of >= early
        out["explain"]["earliest_filing"] = {
            "rule_id": "R-ELIG-EARLY",
            "text_es": (f"La regla dice que puede presentar la solicitud desde {spoken_date_es(early)}, "
                        f"noventa días antes de cumplir cinco años como residente."),
        }
        window = statutory_window(filing, lpr, cfg)
        pp = physical_presence(window, trips, cfg)
        out["presence"] = pp
        out["presence_days"] = pp["presence_days"]
        if not pp["meets_presence"] and filing >= early:
            out["flags"].append({"rule_id": "R-PP-913", "category": "presence_short", "days": pp["presence_days"]})
        if any(t.return_ is None for t in trips):
            out["flags"].append({"rule_id": "R-TRIP-OPEN", "category": "trip_open"})
        out["civics_version"] = civics_version(filing, cfg)
        if dob is not None:
            ex = exemptions(dob, lpr, filing, cfg)
            out["exemptions"] = ex
            out["age_at_filing"] = years_between(dob, filing)
            out["lpr_years_at_filing"] = years_between(lpr, filing)
            if ex["e65_20"]:
                out["explain"]["exemptions"] = {"rule_id": "R-EX-65-20", "text_es": (
                    "Por su edad y sus años de residente, la regla dice que puede hacer una versión más corta "
                    "del examen de cívica, en su idioma, y no tiene que hacer el examen de inglés.")}
            elif ex["e55_15"] or ex["e50_20"]:
                rid = "R-EX-55-15" if ex["e55_15"] else "R-EX-50-20"
                out["explain"]["exemptions"] = {"rule_id": rid, "text_es": (
                    "Por su edad y sus años de residente, la regla dice que puede hacer el examen de cívica "
                    "en español con un intérprete que usted lleve.")}
        addr_from = _current_address_from(facts)
        rd = residence_district(addr_from, filing, cfg)
        if rd:
            out["flags"].append(rd)

    if fees is not None and facts.get("fee.method"):
        try:
            hh = facts.get("fee.household_size")
            inc = facts.get("fee.income")
            out["fee"] = fee(str(facts["fee.method"]), facts.get("fee.benefit_type"),
                             int(hh) if hh not in (None, "") else None,
                             int(inc) if inc not in (None, "") else None, as_of, fees)
        except ValidationError as e:
            out["error"] = {"code": "validation", "field": e.field, "message": e.message}
    return out


def _current_address_from(facts: dict[str, Any]) -> date | None:
    idx = sorted({int(k.split("[")[1].split("]")[0]) for k in facts if k.startswith("addresses[")})
    for i in idx:
        if not facts.get(f"addresses[{i}].to"):
            return _d(facts.get(f"addresses[{i}].from"))
    return None
