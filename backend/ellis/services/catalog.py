"""Field catalog: definitions, labels, required fields and the liaison's fallback queue.

Driven by config/fields.yaml and config/background_questions.yaml.
`cur` everywhere is the case's current facts: {field_key: {"value", "status", "source", "hedge", ...}}.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Any

from ..config import yaml_config
from ..rules.engine import add_years

LIST_RE = re.compile(r"^(?P<list>[a-z_]+)\[(?P<i>\d+)\]\.(?P<sub>[a-z_]+)$")
DEFERRED = "deferred_to_professional"


@lru_cache
def fields_cfg() -> dict[str, Any]:
    return yaml_config("fields.yaml")


@lru_cache
def bg_cfg() -> dict[str, Any]:
    return yaml_config("background_questions.yaml")


@lru_cache
def sections() -> list[dict[str, Any]]:
    return fields_cfg()["sections"]


@lru_cache
def section_label(key: str) -> str:
    for s in sections():
        if s["key"] == key:
            return s["label_es"]
    return key


@lru_cache
def _static() -> dict[str, dict[str, Any]]:
    out = {f["key"]: f for f in fields_cfg()["fields"]}
    for q in bg_cfg()["questions"]:
        out[f"background.{q['key']}"] = {
            "key": f"background.{q['key']}", "section": "background", "type": "yes_no_unsure", "required": True,
            "capture": "V", "confirm": "direct", "material": True, "label_es": q["text_es"], "label_en": q["text_en"],
            "question_es": q["text_es"], "question_en": q["text_en"], "official": True, "bg": q,
        }
    for q in bg_cfg()["oath"]:
        out[f"oath.{q['key']}"] = {
            "key": f"oath.{q['key']}", "section": "oath", "type": "yes_no_unsure", "required": True,
            "capture": "V", "confirm": "direct", "material": True, "label_es": q["text_es"], "label_en": q["text_en"],
            "question_es": q["text_es"], "question_en": q["text_en"], "official": True, "oath": q,
        }
    return out


def lists() -> dict[str, Any]:
    return fields_cfg()["lists"]


def field_def(key: str) -> dict[str, Any] | None:
    """Definition for a field key, including list items like trips[0].return."""
    st = _static()
    if key in st:
        return st[key]
    m = LIST_RE.match(key)
    if m:
        name, i, sub = m["list"], int(m["i"]), m["sub"]
        lcfg = lists().get(name)
        if lcfg:
            if sub == "another":
                return {"key": key, "type": "bool", "section": lcfg["section"], "capture": "V", "confirm": "direct",
                        "label_es": "Otro viaje", "label_en": "Another trip",
                        "question_es": lcfg.get("more_question_es", "¿Hay otro?"), "list": name, "index": i}
            for it in lcfg["item"]:
                if it["key"] == sub:
                    d = dict(it)
                    d.update({"key": key, "section": lcfg["section"], "list": name, "index": i, "sub": sub})
                    d["label_es"] = f"{list_item_label(name, i)}: {it['label_es']}"
                    d["label_en"] = f"{name.rstrip('s').title()} {i + 1}: {it['label_en']}"
                    return d
    for ff in fields_cfg().get("free_fields", []):
        if key.startswith(ff["key_prefix"]):
            return {"key": key, "type": ff["type"], "section": ff["section"], "capture": "V", "confirm": "direct",
                    "label_es": ff["label_es"], "label_en": ff["label_en"], "required": False}
    return None


def list_item_label(name: str, i: int, lang: str = "es") -> str:
    if lang == "en":
        word = {"trips": "Trip", "addresses": "Address", "employment": "Job", "children": "Child"}.get(name, name)
    else:
        word = {"trips": "Viaje", "addresses": "Domicilio", "employment": "Trabajo", "children": "Hijo(a)"}.get(name, name)
    return f"{word} {i + 1}"


def label_es(key: str) -> str:
    d = field_def(key)
    return d["label_es"] if d else key


def label_en(key: str) -> str:
    d = field_def(key)
    return d.get("label_en", key) if d else key


def section_of(key: str) -> str:
    d = field_def(key)
    return d["section"] if d else key.split(".")[0].split("[")[0]


def is_masked(key: str) -> bool:
    d = field_def(key)
    return bool(d and d.get("masked"))


def mask_token(key: str) -> str:
    d = field_def(key) or {}
    return d.get("token", "[REDACTED]")


def is_material(key: str) -> bool:
    d = field_def(key)
    return bool(d and d.get("material"))


def needs_readback(key: str) -> bool:
    d = field_def(key)
    return bool(d and d.get("confirm") == "readback")


def is_date_field(key: str) -> bool:
    d = field_def(key)
    return bool(d and d.get("type") in ("date", "date_or_present"))


def background_question(key: str) -> dict[str, Any] | None:
    d = field_def(key)
    return d.get("bg") if d else None


def group_fields(group: str) -> list[str]:
    return [f"background.{q['key']}" for q in bg_cfg()["questions"] if q.get("group") == group]


def section_for_category(category: str) -> str:
    groups = {"arrest": "criminal_history", "removal": "removal", "citizenship_claim": "citizenship",
              "fraud": "fraud", "danger": "danger"}
    g = groups.get(category)
    return f"background.{g}" if g else "background"


# ---------------------------------------------------------------- required fields

def _val(cur: dict[str, dict], key: str) -> Any:
    f = cur.get(key)
    return None if f is None else f.get("value")


def _has(cur: dict[str, dict], key: str) -> bool:
    f = cur.get(key)
    return f is not None and f.get("status") != "superseded"


def _requires_ok(d: dict[str, Any], cur: dict[str, dict]) -> bool:
    req = d.get("requires")
    if not req:
        return True
    for k, allowed in req.items():
        if _val(cur, k) not in allowed:
            return False
    return True


def _to_date(v: Any) -> date | None:
    if not v or v == "present":
        return None
    s = str(v)
    try:
        if len(s) == 7:
            return date.fromisoformat(s + "-01")
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def list_items_required(name: str, cur: dict[str, dict], derived: dict[str, Any] | None, today: date) -> list[str]:
    """Required item field keys for one list, in conversational order."""
    lcfg = lists()[name]
    out: list[str] = []
    if "requires" in lcfg and not _requires_ok(lcfg, cur):
        return out
    item_keys = [it for it in lcfg["item"] if it.get("capture") != "E" and it.get("required", True) is not False
                 and "required_if_days_gt" not in it]
    if "count_field" in lcfg:
        n = _val(cur, lcfg["count_field"])
        try:
            n = int(n or 0)
        except (TypeError, ValueError):
            n = 0
        for i in range(n):
            out += [f"{name}[{i}].{it['key']}" for it in item_keys]
        return out
    if "coverage_years" in lcfg:
        horizon = add_years(today, -lcfg["coverage_years"])
        i = 0
        while i < 12:
            out += [f"{name}[{i}].{it['key']}" for it in item_keys]
            frm = _to_date(_val(cur, f"{name}[{i}].from"))
            if frm is None or frm <= horizon:
                break
            i += 1
        return out
    # trips: item 0, then "another" after each completed trip
    trip_days = {t["index"]: t["days"] for t in (derived or {}).get("trips", [])}
    i = 0
    while i < 30:
        keys = [f"{name}[{i}].{it['key']}" for it in item_keys]
        for it in lcfg["item"]:
            if "required_if_days_gt" in it and trip_days.get(i, 0) > it["required_if_days_gt"]:
                keys.insert(2, f"{name}[{i}].{it['key']}")
        out += keys
        out.append(f"{name}[{i}].another")
        if _val(cur, f"{name}[{i}].another") is True:
            i += 1
            continue
        break
    return out


def required_fields(cur: dict[str, dict], derived: dict[str, Any] | None, today: date) -> list[str]:
    """All required field keys for this case, in default section order."""
    st = _static()
    by_section: dict[str, list[str]] = {s["key"]: [] for s in sections()}
    for key, d in st.items():
        if not d.get("required"):
            continue
        if not _requires_ok(d, cur):
            continue
        bg = d.get("bg")
        if bg and bg.get("applies_if"):
            if any(_val(cur, k) != v for k, v in bg["applies_if"].items()):
                continue
        by_section[d["section"]].append(key)
    for name, lcfg in lists().items():
        by_section[lcfg["section"]] += list_items_required(name, cur, derived, today)
    out: list[str] = []
    for s in sections():
        out += by_section[s["key"]]
    return out


def missing_required(cur: dict[str, dict], derived: dict[str, Any] | None, today: date, confirmed: bool) -> list[str]:
    miss = []
    for k in required_fields(cur, derived, today):
        f = cur.get(k)
        if f is None:
            miss.append(k)
        elif confirmed and f.get("status") != "confirmed":
            miss.append(k)
    return miss


# ---------------------------------------------------------------- fallback queue

def needs_confirmation(key: str, f: dict[str, Any]) -> bool:
    if f.get("status") == "confirmed":
        return False
    if f.get("value") == DEFERRED:
        return False
    d = field_def(key) or {}
    if d.get("capture") in ("S", "P", "E"):
        return False
    if f.get("status") == "disputed":
        return True
    return (d.get("confirm") == "readback" or f.get("hedge") or f.get("source") == "document"
            or f.get("third_party"))


def fallback_queue(cur: dict[str, dict], derived: dict[str, Any] | None, today: date,
                   deferred_sections: set[str] | None = None, limit: int = 80) -> list[dict[str, Any]]:
    """Remaining required fields in catalog order, as briefing-style queue items."""
    deferred_sections = deferred_sections or set()
    items: list[dict[str, Any]] = []
    biographics_pending = False
    for key in required_fields(cur, derived, today):
        d = field_def(key) or {}
        if d.get("capture") == "E":
            continue
        f = cur.get(key)
        if f is not None and f.get("value") == DEFERRED:
            continue
        if f is None:
            cap = d.get("capture", "V")
            if cap == "P":
                if not biographics_pending:
                    items.append({"kind": "request_biographics", "section": "biographics", "reason": "screen pickers"})
                    biographics_pending = True
                continue
            if cap.startswith("S"):
                items.append({"kind": "request_secure_entry", "field": key, "section": d["section"],
                              "reason": "sensitive value is typed, never spoken"})
                continue
            if cap == "D":
                items.append({"kind": "request_upload", "document_type": d.get("upload", "other"), "field": key,
                              "section": d["section"], "reason": "only a document provides this"})
                continue
            items.append({"kind": "ask", "field": key, "section": d["section"], "reason": "next required field"})
        elif needs_confirmation(key, f):
            items.append({"kind": "read_back", "field": key, "section": d["section"],
                          "reason": "confirm before it counts",
                          "read_value": "document" if d.get("document_authoritative") else "applicant"})
        if len(items) >= limit:
            break
    return items


def question_for(key: str, cur: dict[str, dict] | None = None, lang: str = "es") -> str:
    d = field_def(key) or {}
    prev_key, q_key, label_key = (
        ("question_prev_en", "question_en", "label_en") if lang == "en" else
        ("question_prev_es", "question_es", "label_es"))
    if d.get("list") and d.get("index", 0) > 0 and d.get(prev_key):
        q = d[prev_key]
    elif d.get(q_key):
        q = d[q_key]
    elif lang == "en":
        q = f"Can you tell me {d.get(label_key, key).lower()}?"
    else:
        q = f"¿Me puede decir {d.get(label_key, key).lower()}?"
    return q.replace("{n}", str(d.get("index", 0) + 1))
