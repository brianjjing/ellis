"""Rules engine unit tests T1–T18 (spec) plus branch-coverage tests."""

from datetime import date

import pytest

from ellis.config import fee_config, rule_config
from ellis.rules import engine as E
from ellis.rules.engine import Trip, ValidationError

CFG = rule_config()
FEES = fee_config()


def d(s):
    return date.fromisoformat(s)


# T1 / T2 ------------------------------------------------------------------
def test_t1_maria_hedged_date():
    t = Trip(d("2023-08-03"), d("2024-03-03"))
    assert E.trip_days(t.departure, t.return_, CFG) == 213
    assert [f["rule_id"] for f in E.absence_flags([t], CFG)] == ["R-ABS-180"]


def test_t2_maria_corrected():
    t = Trip(d("2023-08-03"), d("2024-03-13"))
    assert E.trip_days(t.departure, t.return_, CFG) == 223
    assert [f["rule_id"] for f in E.absence_flags([t], CFG)] == ["R-ABS-180"]


# T3 / T4 / T5 ---------------------------------------------------------------
def test_t3_maria_presence():
    w = E.statutory_window(d("2026-10-10"), d("2022-01-15"), CFG)
    assert w == (d("2022-01-15"), d("2026-10-10"))
    pp = E.physical_presence(w, [Trip(d("2023-08-03"), d("2024-03-13"))], CFG)
    assert pp["window_days"] == 1729
    assert pp["days_abroad"] == 223
    assert pp["presence_days"] == 1506
    assert pp["meets_presence"] is True


def test_t4_maria_early_filing():
    assert E.anniversary(d("2022-01-15"), 5) == d("2027-01-15")
    assert E.earliest_filing(d("2022-01-15"), CFG) == d("2026-10-17")


def test_t5_ana_early_filing():
    assert E.anniversary(d("2020-06-02"), 5) == d("2025-06-02")
    assert E.earliest_filing(d("2020-06-02"), CFG) == d("2025-03-04")


# T6 / T7 --------------------------------------------------------------------
ROSA_TRIPS = [
    Trip(d("2021-12-01"), d("2022-02-15"), 0),   # 76
    Trip(d("2022-11-20"), d("2023-03-05"), 1),   # 105
    Trip(d("2023-11-25"), d("2024-03-18"), 2),   # 114
    Trip(d("2024-11-22"), d("2025-03-17"), 3),   # 115
    Trip(d("2025-11-20"), d("2026-03-09"), 4),   # 109
]


def test_t6_rosa_presence():
    assert [E.trip_days(t.departure, t.return_, CFG) for t in ROSA_TRIPS] == [76, 105, 114, 115, 109]
    w = E.statutory_window(d("2026-11-15"), d("2008-03-10"), CFG)
    assert w == (d("2021-11-15"), d("2026-11-15"))
    pp = E.physical_presence(w, ROSA_TRIPS, CFG)
    assert pp["window_days"] == 1826
    assert pp["days_abroad"] == 519
    assert pp["presence_days"] == 1307
    assert E.absence_flags(ROSA_TRIPS, CFG) == []


def test_t7_rosa_exemptions():
    ex = E.exemptions(d("1965-02-14"), d("2008-03-10"), d("2026-11-15"), CFG)
    assert ex == {"e50_20": False, "e55_15": True, "e65_20": False}


# T8 – T11 -------------------------------------------------------------------
def test_t8_leap_day():
    assert E.trip_days(d("2024-02-28"), d("2024-03-01"), CFG) == 2


def test_t9_trip_across_window_start():
    window = (d("2021-11-15"), d("2026-11-15"))
    abroad, _ = E.days_abroad([Trip(d("2021-10-01"), d("2021-12-01"))], window, CFG)
    assert abroad == 16


def test_t10_boundary_180():
    t = Trip(d("2024-01-01"), d("2024-06-29"))
    assert E.trip_days(t.departure, t.return_, CFG) == 180
    assert E.absence_flags([t], CFG) == []


def test_t11_boundary_365():
    t = Trip(d("2023-01-01"), d("2024-01-01"))
    assert E.trip_days(t.departure, t.return_, CFG) == 365
    assert [f["rule_id"] for f in E.absence_flags([t], CFG)] == ["R-ABS-365"]


# T12 / T13 ------------------------------------------------------------------
def test_t12_return_before_departure():
    with pytest.raises(ValidationError) as e:
        E.validate([Trip(d("2024-03-01"), d("2024-02-01"), 3)], None, None, d("2026-10-23"))
    assert e.value.field == "trips[3].return"


def test_t13_overlap():
    trips = [Trip(d("2024-01-01"), d("2024-02-01"), 0), Trip(d("2024-01-31"), d("2024-02-10"), 1)]
    with pytest.raises(ValidationError):
        E.validate(trips, None, None, d("2026-10-23"))


# T14 / T15 ------------------------------------------------------------------
def test_t14_civics_cutoff():
    assert E.civics_version(d("2025-10-19"), CFG) == "2008-100"
    assert E.civics_version(d("2025-10-20"), CFG) == "2025-128"


def test_t15_open_trip():
    as_of = d("2026-10-23")
    window = (d("2021-10-23"), as_of)
    abroad, rules = E.days_abroad([Trip(d("2026-09-01"), None)], window, CFG)
    assert abroad == 52
    assert "R-TRIP-OPEN" in rules
    out = E.evaluate({"lpr_since": "2020-01-01", "trips[0].departure": "2026-09-01"}, as_of, CFG)
    assert out["trips"][0] == {"index": 0, "days": 52, "open": True}
    assert any(f["rule_id"] == "R-TRIP-OPEN" for f in out["flags"])


# T16 / T17 ------------------------------------------------------------------
def test_t16_fee_online_standard():
    r = E.fee("online", None, None, None, d("2026-10-26"), FEES)
    assert r["amount"] == 710
    assert r["fee_table_version"] == "fees-2024-04"


def test_t17_fee_waiver_requires_paper():
    r = E.fee("online", "medicaid", None, None, d("2026-10-26"), FEES)
    assert r["error"] == "waiver_requires_paper"
    assert r["paper_option"]["amount"] == 0
    assert r["paper_option"]["form"] == "I-912"
    assert r["paper_option"]["paper_only"] is True


# T18 ------------------------------------------------------------------------
def test_t18_determinism():
    facts = {"lpr_since": "2022-01-15", "dob": "1988-05-02", "trips[0].departure": "2023-08-03",
             "trips[0].return": "2024-03-13"}
    a = E.evaluate(facts, d("2026-10-23"), CFG, FEES)
    b = E.evaluate(dict(facts), d("2026-10-23"), CFG, FEES)
    assert a == b
    assert a["inputs_hash"] == b["inputs_hash"]


# ---------------------------------------------------------------- flows checks

def test_maria_flow_numbers():
    base = {"lpr_since": "2022-01-15", "trips[0].departure": "2023-08-03"}
    a = E.evaluate({**base, "trips[0].return": "2024-03-03"}, d("2026-10-23"), CFG)
    assert a["trip_days"] == 213 and a["presence_days"] == 1529
    assert a["earliest_filing"] == "2026-10-17" and a["window_open"] is True
    assert any(f["category"] == "absence_gt_180" for f in a["flags"])
    b = E.evaluate({**base, "trips[0].return": "2024-03-13"}, d("2026-10-23"), CFG)
    assert b["trip_days"] == 223 and b["presence_days"] == 1519


def test_rosa_evaluate_no_absence_flag():
    facts = {"lpr_since": "2008-03-10", "dob": "1965-02-14", "filing.planned_date": "2026-11-15"}
    for t in ROSA_TRIPS:
        facts[f"trips[{t.index}].departure"] = t.departure.isoformat()
        facts[f"trips[{t.index}].return"] = t.return_.isoformat()
    out = E.evaluate(facts, d("2026-10-23"), CFG)
    assert out["presence_days"] == 1307
    assert out["exemptions"]["e55_15"] is True
    assert not [f for f in out["flags"] if f["category"].startswith("absence")]
    assert out["explain"]["exemptions"]["rule_id"] == "R-EX-55-15"


# ---------------------------------------------------------------- branch coverage

def test_exclude_travel_days_convention():
    cfg = E.RuleConfig(version="x", trip_day_convention="exclude_travel_days")
    assert E.trip_days(d("2023-08-03"), d("2024-03-13"), cfg) == 222
    assert E.trip_days(d("2024-01-01"), d("2024-01-01"), cfg) == 0


def test_add_years_leap():
    assert E.add_years(d("2024-02-29"), 1) == d("2025-02-28")
    assert E.anniversary(d("2020-02-29"), 5) == d("2025-02-28")


def test_years_between():
    assert E.years_between(d("1965-02-14"), d("2026-02-13")) == 60
    assert E.years_between(d("1965-02-14"), d("2026-02-14")) == 61


def test_days_abroad_outside_window_and_clipped_end():
    window = (d("2022-01-01"), d("2023-01-01"))
    abroad, _ = E.days_abroad([Trip(d("2021-01-01"), d("2021-02-01"))], window, CFG)
    assert abroad == 0
    abroad, _ = E.days_abroad([Trip(d("2022-12-01"), d("2023-02-01"))], window, CFG)
    assert abroad == 31


def test_absence_flags_open_trip_without_as_of_is_skipped():
    assert E.absence_flags([Trip(d("2024-01-01"), None)], CFG) == []
    flags = E.absence_flags([Trip(d("2024-01-01"), None)], CFG, as_of=d("2025-06-01"))
    assert flags[0]["rule_id"] == "R-ABS-365"


def test_presence_short_flag():
    facts = {"lpr_since": "2021-01-01", "trips[0].departure": "2022-01-01", "trips[0].return": "2025-01-01"}
    out = E.evaluate(facts, d("2026-10-23"), CFG)
    cats = {f["category"] for f in out["flags"]}
    assert "presence_short" in cats and "absence_gte_365" in cats


def test_residence_district():
    assert E.residence_district(None, d("2026-10-23"), CFG) is None
    assert E.residence_district(d("2026-09-01"), d("2026-10-23"), CFG)["rule_id"] == "R-RES-3M"
    assert E.residence_district(d("2026-01-01"), d("2026-10-23"), CFG) is None
    # month wraps to previous year, and day clamps (May 31 -> Feb 28)
    assert E.residence_district(d("2025-12-01"), d("2026-02-15"), CFG)["rule_id"] == "R-RES-3M"
    assert E.residence_district(d("2026-03-01"), d("2026-05-31"), CFG) is not None


def test_evaluate_residence_flag_from_addresses():
    facts = {"lpr_since": "2020-01-01", "addresses[0].from": "2026-09-01",
             "addresses[1].from": "2019-01-01", "addresses[1].to": "2026-09-01"}
    out = E.evaluate(facts, d("2026-10-23"), CFG)
    assert any(f["rule_id"] == "R-RES-3M" for f in out["flags"])
    out = E.evaluate({"lpr_since": "2020-01-01", "addresses[0].from": "2019-01-01", "addresses[0].to": "2020-01-01"},
                     d("2026-10-23"), CFG)
    assert not any(f["rule_id"] == "R-RES-3M" for f in out["flags"])


def test_exemption_explains():
    out = E.evaluate({"lpr_since": "1990-01-01", "dob": "1950-01-01"}, d("2026-10-23"), CFG)
    assert out["explain"]["exemptions"]["rule_id"] == "R-EX-65-20"
    out = E.evaluate({"lpr_since": "2000-01-01", "dob": "1974-01-01"}, d("2026-10-23"), CFG)
    assert out["explain"]["exemptions"]["rule_id"] == "R-EX-50-20"
    out = E.evaluate({"lpr_since": "2020-01-01", "dob": "1990-01-01"}, d("2026-10-23"), CFG)
    assert "exemptions" not in out["explain"]


def test_validation_errors_surface_in_evaluate():
    as_of = d("2026-10-23")
    out = E.evaluate({"trips[0].departure": "2027-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "trips[0].departure"
    out = E.evaluate({"trips[0].departure": "2026-01-01", "trips[0].return": "2027-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "trips[0].return"
    out = E.evaluate({"lpr_since": "2027-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "lpr_since"
    out = E.evaluate({"lpr_since": "1980-01-01", "dob": "1990-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "lpr_since"
    out = E.evaluate({"lpr_since": "2025-01-01", "dob": "1800-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "lpr_since"
    out = E.evaluate({"dob": "2030-01-01"}, as_of, CFG)
    assert out["error"]["field"] == "dob"
    # an open trip followed by another trip overlaps
    out = E.evaluate({"trips[0].departure": "2026-01-01", "trips[1].departure": "2026-02-01",
                      "trips[1].return": "2026-03-01"}, as_of, CFG)
    assert out["error"]["code"] == "validation"


def test_partial_dates_and_skipped_trips():
    out = E.evaluate({"lpr_since": "2019-06", "trips[0].return": "2024-01-01"}, d("2026-10-23"), CFG,
                     low_confidence_fields={"lpr_since"})
    assert out["anniversary"] == "2024-06-01"
    assert out["low_confidence"] is True
    assert out["trips"] == []
    assert E._d("2020") == d("2020-01-01")
    assert E._d(d("2020-02-02")) == d("2020-02-02")
    assert E._d("") is None


def test_fee_branches():
    as_of = d("2026-10-26")
    with pytest.raises(ValidationError):
        E.fee("fax", None, None, None, as_of, FEES)
    assert E.fee("paper", None, None, None, as_of, FEES)["amount"] == 760
    w = E.fee("paper", "Medi-Cal", None, None, as_of, FEES)
    assert w["amount"] == 0 and w["form"] == "I-912" and w["waiver_candidate"]
    assert w["fallback"]["amount"] == 760  # no income given -> no reduced fallback
    w = E.fee("paper", "medicaid", 2, 20000, as_of, FEES)
    assert w["fallback"]["amount"] == 380
    w = E.fee("paper", None, 1, 20000, as_of, FEES)  # <= 150% FPG
    assert w["basis"] == "income_150_fpg"
    r = E.fee("paper", None, 1, 50000, as_of, FEES)  # <= 400% FPG
    assert r["amount"] == 380 and r["paper_only"]
    r = E.fee("online", None, 1, 50000, as_of, FEES)
    assert r["amount"] == 710 and r["paper_option"]["amount"] == 380
    r = E.fee("paper", None, 1, 90000, as_of, FEES)
    assert r["amount"] == 760


def test_evaluate_fee_and_errors():
    out = E.evaluate({"fee.method": "online"}, d("2026-10-26"), CFG, FEES)
    assert out["fee"]["amount"] == 710
    out = E.evaluate({"fee.method": "paper", "fee.household_size": "2", "fee.income": ""}, d("2026-10-26"), CFG, FEES)
    assert out["fee"]["amount"] == 760
    out = E.evaluate({"fee.method": "fax"}, d("2026-10-26"), CFG, FEES)
    assert out["error"]["field"] == "fee.method"


def test_spoken_forms():
    assert E.spoken_date_es(d("2022-01-15")) == "el quince de enero de dos mil veintidós"
    assert E.spoken_date_es(d("2024-03-13")) == "el trece de marzo de dos mil veinticuatro"
    assert E.spoken_date_es(d("2000-07-01")) == "el primero de julio de dos mil"
    assert E.year_es(1965) == "mil novecientos sesenta y cinco"
    assert E.year_es(1900) == "mil novecientos"
    assert E.year_es(1950) == "mil novecientos cincuenta"
    assert E.year_es(2001) == "dos mil uno"
    assert E.year_es(1941) == "mil novecientos cuarenta y uno"
    assert E.short_date_es(d("2026-10-17")) == "17 de octubre de 2026"


def test_config_from_dict_accepts_string_cutoff():
    raw = {"version": "t", "paths": {"5yr": {"years_lpr": 5, "physical_presence_days": 913, "early_filing_days": 90,
                                              "district_months": 3}},
           "absence": {"rebuttable_days_gt": 180, "breaks_days_gte": 365},
           "exemptions": {}, "civics": {"cutoff_2025_test": "2025-10-20"}}
    assert E.RuleConfig.from_dict(raw).civics_cutoff == d("2025-10-20")
