"""The Case API's domain logic. The only writer to the database; every write appends events.

Agents propose; this module validates and writes with provenance. Corrections supersede, never overwrite.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import fee_config, rule_config, settings
from ..db import (
    Briefing, CallSession, Case, Derived, Document, Event, Extraction, Fact, Flag, Gap, Memo, Packet, ReviewItem,
    Signoff, Task, Utterance, VaultValue, now,
)
from ..rules import engine as rules
from . import catalog, keywords, vault
from .bus import queue_after_commit
from .flags import CATEGORIES, FLAG_CONTINUE, RULE_TRIGGERS, STOP_NOW, category as cat_info
from .values import ValueError_, equal, normalize

READBACK_WINDOW_S = 120


class CaseError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.field, self.status = code, message, field, status


def today() -> date:
    if settings.today_override:
        return date.fromisoformat(settings.today_override)
    return date.today()


def case_lang(case: Case) -> str:
    return "en" if (case.language or "").startswith("en") else "es"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------- events

def emit(s: Session, case: Case | None, kind: str, payload: dict[str, Any] | None = None,
         actor_type: str = "system", actor: str = "case_api", clinic_id: str | None = None) -> Event:
    ev = Event(clinic_id=case.clinic_id if case else clinic_id, case_id=case.id if case else None, kind=kind,
               payload=payload or {}, actor_type=actor_type, actor=actor, ts=now())
    s.add(ev)
    s.flush()
    if case is not None:
        case.last_event_at = ev.ts
    queue_after_commit(s, {"id": ev.id, "clinic_id": ev.clinic_id, "case_id": ev.case_id, "kind": kind,
                           "payload": ev.payload, "actor_type": actor_type, "actor": actor, "ts": ev.ts.isoformat()})
    return ev


def push(s: Session, case: Case, kind: str, payload: dict[str, Any]) -> None:
    """Transient push to the applicant client (not an audit event), delivered after commit."""
    queue_after_commit(s, {"id": None, "clinic_id": case.clinic_id, "case_id": case.id, "kind": kind,
                           "payload": payload, "actor_type": "system", "actor": "case_api", "transient": True})


# ---------------------------------------------------------------- facts

def facts_for(s: Session, case_id: str, field: str | None = None, include_superseded: bool = False) -> list[Fact]:
    q = select(Fact).where(Fact.case_id == case_id)
    if field is not None:
        q = q.where(Fact.field == field)
    if not include_superseded:
        q = q.where(Fact.status != "superseded")
    return list(s.scalars(q.order_by(Fact.ts, Fact.id)))


def current_facts(s: Session, case_id: str) -> dict[str, Fact]:
    """Latest non-superseded fact per field, preferring non-disputed."""
    by: dict[str, list[Fact]] = {}
    for f in facts_for(s, case_id):
        by.setdefault(f.field, []).append(f)
    out = {}
    for k, fs in by.items():
        good = [f for f in fs if f.status != "disputed"]
        out[k] = (good or fs)[-1]
    return out


def cur_view(s: Session, case_id: str) -> dict[str, dict[str, Any]]:
    by: dict[str, list[Fact]] = {}
    for f in facts_for(s, case_id):
        by.setdefault(f.field, []).append(f)
    out = {}
    for k, fs in by.items():
        good = [f for f in fs if f.status != "disputed"]
        f = (good or fs)[-1]
        out[k] = {"id": f.id, "value": f.value, "status": f.status, "source": f.source, "hedge": f.hedge,
                  "third_party": f.third_party, "conflict": len(fs) > 1}
    return out


def fact_values(s: Session, case_id: str, masked: bool = True) -> dict[str, Any]:
    return {k: v["value"] for k, v in cur_view(s, case_id).items()}


def consent_given(s: Session, case: Case) -> bool:
    ev = s.scalars(select(Event).where(Event.case_id == case.id, Event.kind == "consent.given")
                   .order_by(Event.id.desc()).limit(1)).first()
    return ev is not None and ev.payload.get("disclosure_version") == case.disclosure_version


def fact_dict(f: Fact) -> dict[str, Any]:
    return {"id": f.id, "field": f.field, "value": f.value, "status": f.status, "source": f.source,
            "hedge": f.hedge, "supersedes": f.supersedes, "matches_document": f.matches_document,
            "third_party": f.third_party}


def _supersede(others: list[Fact], by: Fact | None, note: str | None = None) -> None:
    for o in others:
        if by is not None and o.id == by.id:
            continue
        o.status = "superseded"
        o.superseded_by = by.id if by else None
        if note:
            o.note = (o.note + "; " if o.note else "") + note


def _insert_fact(s: Session, case: Case, field: str, value: Any, status: str, source: str, *, hedge=False,
                 provenance: dict | None = None, proposed_by: str = "applicant", supersedes: str | None = None,
                 third_party: bool = False, matches_document: str | None = None, note: str | None = None,
                 confidence: str | None = None) -> Fact:
    f = Fact(clinic_id=case.clinic_id, case_id=case.id, field=field, value=value, status=status, source=source,
             hedge=hedge, provenance=provenance or {}, proposed_by=proposed_by, supersedes=supersedes,
             third_party=third_party, matches_document=matches_document, note=note, confidence=confidence, ts=now())
    if status == "confirmed":
        f.confirmed_at = f.ts
    s.add(f)
    s.flush()
    return f


def _mark_material(case: Case, field: str) -> None:
    if catalog.is_material(field) or field.startswith("background.") or field.startswith("trips["):
        case.material_changed_at = now()


# ---------------------------------------------------------------- documents as evidence

def _doc_quality(s: Session, doc_id: str | None) -> str | None:
    if not doc_id:
        return None
    d = s.get(Document, doc_id)
    return d.quality if d else None


def document_candidates(s: Session, case_id: str, field: str) -> list[dict[str, Any]]:
    """Values documents assert for this field: [{value, document_id, quality, kind}]."""
    out = []
    for f in facts_for(s, case_id, field, include_superseded=True):
        if f.source == "document":
            doc_id = f.provenance.get("document_id")
            out.append({"value": f.value, "document_id": doc_id, "quality": _doc_quality(s, doc_id), "kind": "fact"})
    m = catalog.LIST_RE.match(field)
    if m and m["list"] == "trips" and m["sub"] in ("departure", "return"):
        direction = "entry" if m["sub"] == "return" else "exit"
        for x in s.scalars(select(Extraction).where(Extraction.case_id == case_id)):
            for st in (x.data or {}).get("stamps", []) or []:
                if st.get("direction") == direction and st.get("date"):
                    out.append({"value": st["date"], "document_id": x.document_id, "quality": x.quality, "kind": "stamp"})
    return out


def _doc_check(s: Session, case_id: str, field: str, value: Any) -> tuple[str | None, list[dict]]:
    """(matching high-quality doc id, conflicting high-quality candidates)."""
    cands = [c for c in document_candidates(s, case_id, field) if c["quality"] == "high"]
    match = next((c["document_id"] for c in cands if equal(field, c["value"], value)), None)
    conflicts = []
    for c in cands:
        if equal(field, c["value"], value):
            continue
        if c["kind"] == "stamp":
            # a stamp only conflicts with a nearby spoken date (same trip)
            try:
                gap = abs((date.fromisoformat(str(c["value"])[:10]) - date.fromisoformat(str(value)[:10]).replace()).days)
            except ValueError:
                continue
            if gap <= 31:
                conflicts.append(c)
        else:
            conflicts.append(c)
    if match:
        conflicts = []
    return match, conflicts


# ---------------------------------------------------------------- utterances (layer 4)

def applicant_turn(s: Session, case: Case, text: str, session_id: str | None = None,
                   meta: dict | None = None) -> dict[str, Any]:
    """Store an applicant turn after the in-loop checks. Raw stop-list text is never written anywhere."""
    stop = keywords.stop_hit(text)
    if stop:
        u = Utterance(clinic_id=case.clinic_id, case_id=case.id, session_id=session_id, speaker="applicant",
                      text=f"[STOP:{stop}]", redacted=True, meta={"stop": True})
        s.add(u)
        s.flush()
        res = stop_now(s, case, stop, layer=4, session_id=session_id)
        return {"utterance_id": u.id, "stop": stop, "redacted": True, "flags": [], **res}
    redacted = keywords.has_sensitive_number(text)
    stored = keywords.redact_numbers(text) if redacted else text
    u = Utterance(clinic_id=case.clinic_id, case_id=case.id, session_id=session_id, speaker="applicant",
                  text=stored, redacted=redacted, meta=meta or {})
    s.add(u)
    s.flush()
    if redacted:
        emit(s, case, "utterance.redacted", {"utterance_id": u.id, "reason": "sensitive_number"}, "liaison", "liaison")
    flags = []
    for cat in keywords.flag_hits(text):
        fl = raise_flag(s, case, cat, layer=4, detail={"utterance_id": u.id})
        if fl is not None:
            flags.append(flag_dict(fl, applicant=True))
    return {"utterance_id": u.id, "stop": None, "redacted": redacted, "text": stored, "flags": flags}


def liaison_utterance(s: Session, case: Case, text: str, session_id: str | None = None, locked: bool = False,
                      meta: dict | None = None) -> Utterance:
    u = Utterance(clinic_id=case.clinic_id, case_id=case.id, session_id=session_id, speaker="liaison",
                  text=text, locked=locked, meta=meta or {})
    s.add(u)
    s.flush()
    return u


# ---------------------------------------------------------------- read-back

def open_readback(s: Session, case: Case, field: str) -> Event | None:
    evs = list(s.scalars(select(Event).where(Event.case_id == case.id,
                                             Event.kind.in_(["readback.started", "readback.closed"]))
                         .order_by(Event.id.desc()).limit(20)))
    for ev in evs:
        if ev.payload.get("field") != field:
            continue
        if ev.kind == "readback.closed":
            return None
        if now() - _aware(ev.ts) <= timedelta(seconds=READBACK_WINDOW_S):
            return ev
        return None
    return None


def read_back(s: Session, case: Case, field: str, briefing_version: int | None = None,
              read_value: str | None = None, lang: str = "es") -> dict[str, Any]:
    d = catalog.field_def(field)
    if d is None:
        raise CaseError("unknown_field", f"unknown field {field}", field)
    if catalog.is_masked(field):
        raise CaseError("masked_field", "sensitive values are never read aloud", field)
    facts = facts_for(s, case.id, field)
    if not facts:
        raise CaseError("no_fact", "nothing to read back for this field", field, 404)
    # Which value: the document's when a high-quality document conflicts (document outranks recall),
    # unless the briefing asks to read the applicant's own value (to avoid leading, F1.11).
    doc_facts = [f for f in facts if f.source == "document" and _doc_quality(s, f.provenance.get("document_id")) == "high"]
    spoken = [f for f in facts if f.source != "document"]
    if read_value == "applicant" and spoken:
        chosen = spoken[-1]
    elif doc_facts and (read_value == "document" or d.get("document_authoritative") or not spoken):
        chosen = doc_facts[-1]
    else:
        chosen = current_facts(s, case.id)[field]
    spoken_form = spoken_value(field, chosen.value, lang=lang)
    emit(s, case, "readback.started", {"field": field, "fact_id": chosen.id, "value": chosen.value,
                                       "briefing_version": briefing_version, "source": chosen.source},
         "liaison", "liaison")
    return {"fact_id": chosen.id, "field": field, "value": chosen.value, "spoken": spoken_form,
            "source": chosen.source, "label_es": catalog.label_es(field),
            "sentence_es": f"Le leo {readback_label(field, chosen.source)}: {spoken_form}. ¿Es correcto?"}


def readback_label(field: str, source: str, lang: str = "es") -> str:
    d = catalog.field_def(field) or {}
    if lang == "en":
        base = d.get("label_en", field).lower()
        return (f"what your document says about {base}" if source == "document"
                else f"what you told me about {base}")
    base = d.get("label_es", field).lower()
    if source == "document":
        return f"lo que dice su documento sobre {base}"
    return f"lo que me dio sobre {base}"


def spoken_value(field: str, value: Any, lang: str = "es") -> str:
    none_word = "none" if lang == "en" else "ninguno"
    if value is None:
        return none_word
    if catalog.is_date_field(field) and isinstance(value, str):
        if value == "present":
            return "the present" if lang == "en" else "el presente"
        if len(value) == 10:
            return rules.spoken_date(date.fromisoformat(value), lang=lang)
        if len(value) == 7:
            y, m = value.split("-")
            months = rules.MONTHS_EN if lang == "en" else rules.MONTHS_ES
            return f"{months[int(m) - 1]} {y}" if lang == "en" else f"{months[int(m) - 1]} de {rules.year_es(int(y))}"
    if isinstance(value, bool):
        return ("yes" if value else "no") if lang == "en" else ("sí" if value else "no")
    if isinstance(value, list):
        return ", ".join(value) if value else none_word
    if value in ("yes", "no", "not_sure"):
        if lang == "en":
            return {"yes": "yes", "no": "no", "not_sure": "not sure"}[value]
        return {"yes": "sí", "no": "no", "not_sure": "no está seguro"}[value]
    d = catalog.field_def(field) or {}
    if d.get("type") == "enum":
        table = ENUM_EN if lang == "en" else ENUM_ES
        return table.get(str(value), str(value))
    return str(value)


ENUM_ES = {
    "single": "soltero o soltera", "married": "casado o casada", "divorced": "divorciado o divorciada",
    "widowed": "viudo o viuda", "separated": "separado o separada", "annulled": "matrimonio anulado",
    "online": "en línea", "paper": "en papel", "us_citizen": "ciudadano estadounidense", "lpr": "residente permanente",
    "other": "otro", "biological": "biológico", "stepchild": "hijastro", "adopted": "adoptado",
    "female": "femenino", "male": "masculino",
}

ENUM_EN = {
    "single": "single", "married": "married", "divorced": "divorced", "widowed": "widowed",
    "separated": "separated", "annulled": "annulled marriage", "online": "online", "paper": "on paper",
    "us_citizen": "a U.S. citizen", "lpr": "a permanent resident", "other": "other", "biological": "biological",
    "stepchild": "stepchild", "adopted": "adopted", "female": "female", "male": "male",
}


# ---------------------------------------------------------------- record_fact

def record_fact(s: Session, case: Case, field: str, value: Any, *, hedge: bool = False,
                utterance_id: str | None = None, utterance_text: str | None = None, session_id: str | None = None,
                source: str = "spoken", actor: str = "liaison", actor_type: str = "liaison",
                is_correction: bool = False, interrupted_at_word: str | None = None,
                third_party: bool | None = None, provenance: dict | None = None) -> dict[str, Any]:
    t0 = datetime.now()
    d = catalog.field_def(field)
    if d is None:
        raise CaseError("unknown_field", f"unknown field {field}", field)
    # (1) consent first
    if field != "consent" and not consent_given(s, case):
        raise CaseError("consent_required", "no fact is accepted before consent", field, 409)
    if catalog.is_masked(field) and source == "spoken":
        raise CaseError("use_secure_entry", "sensitive values are typed on screen, never spoken", field)
    # (2) validate
    try:
        value = normalize(field, value)
    except ValueError_ as e:
        raise CaseError("invalid_value", str(e), field) from None
    if field in _deferred_fields(s, case):
        raise CaseError("deferred_to_professional", "this section is handled by a licensed professional", field, 409)
    # (3) utterance (layer 4 again on stored text)
    if utterance_text and not utterance_id:
        t = applicant_turn(s, case, utterance_text, session_id)
        if t["stop"]:
            return {"saved": False, "stopped": True, "script_key": "stop", "flags": []}
        utterance_id = t["utterance_id"]
    if third_party is None and session_id:
        sess = s.get(CallSession, session_id)
        third_party = bool(sess and sess.third_party_present)
    third_party = bool(third_party)
    prov = {**(provenance or {}), **({"utterance_id": utterance_id} if utterance_id else {}),
            **({"session_id": session_id} if session_id else {})}

    if field == "consent":
        return _record_consent(s, case, value, utterance_id, session_id, third_party, actor_type, actor)

    rb = open_readback(s, case, field)
    existing_all = facts_for(s, case.id, field)
    cur = current_facts(s, case.id).get(field)
    doc_match, doc_conflicts = _doc_check(s, case.id, field, value)
    events: list[tuple[str, dict]] = []
    resolved: list[str] = []
    new_flags: list[Flag] = []
    fact: Fact

    def status_for_new() -> str:
        if doc_match:
            return "confirmed"
        if doc_conflicts and any(c["kind"] == "fact" for c in doc_conflicts):
            return "disputed"
        if third_party or hedge or doc_conflicts:
            return "proposed"
        if d.get("confirm") == "readback" or source == "applicant_typed":
            return "proposed"
        return "confirmed"

    if rb is not None:
        read_val = rb.payload.get("value")
        if equal(field, value, read_val) and not hedge:
            target = next((f for f in existing_all if f.id == rb.payload.get("fact_id")), cur)
            if target is not None and target.source == "document":
                fact = _insert_fact(s, case, field, value, "confirmed", source, provenance=prov,
                                    proposed_by=actor, supersedes=target.id,
                                    matches_document=target.provenance.get("document_id"),
                                    note="confirmed by applicant read-back (document + voice)")
                _supersede(existing_all, fact, "confirmed by read-back")
            elif target is not None:
                target.status = "confirmed"
                target.confirmed_at = now()
                target.third_party = False
                prov_t = dict(target.provenance)
                prov_t["confirmed_by_utterance"] = utterance_id
                target.provenance = prov_t
                fact = target
                _supersede(existing_all, fact, "applicant confirmed the other value in read-back")
            else:  # pragma: no cover - read-back always has a fact
                fact = _insert_fact(s, case, field, value, "confirmed", source, provenance=prov, proposed_by=actor)
            events.append(("fact.confirmed", {"field": field, "fact_id": fact.id, "via": "readback"}))
        elif equal(field, value, read_val) and hedge:
            fact = cur  # "no sé" / hedged yes: stays proposed
            events.append(("readback.unconfirmed", {"field": field}))
        else:
            status = status_for_new()
            if status == "proposed" and not (hedge or third_party or doc_conflicts):
                status = "confirmed"  # corrected inside a read-back
            old = cur.value if cur else None
            fact = _insert_fact(s, case, field, value, status, source, hedge=hedge, provenance=prov,
                                proposed_by=actor, supersedes=cur.id if cur else None, third_party=third_party,
                                matches_document=doc_match)
            _supersede(existing_all, fact, "corrected by applicant")
            events.append(("fact.corrected", {"field": field, "old": old, "new": value, "fact_id": fact.id,
                                              "cause": "barge_in" if interrupted_at_word else "readback_no",
                                              "interrupted_at_word": interrupted_at_word}))
        emit(s, case, "readback.closed", {"field": field}, actor_type, actor)
    else:
        same = cur is not None and equal(field, cur.value, value)
        if same and cur.status == "confirmed":
            fact = cur
        elif same and cur.source == "document" and doc_match and not third_party:
            fact = _insert_fact(s, case, field, value, "confirmed", source, provenance=prov, proposed_by=actor,
                                supersedes=cur.id, matches_document=doc_match, note="matches document")
            _supersede(existing_all, fact)
            events.append(("fact.confirmed", {"field": field, "fact_id": fact.id, "via": "document_match"}))
        elif same and cur.status == "proposed" and status_for_new() == "confirmed":
            cur.status = "confirmed"
            cur.confirmed_at = now()
            fact = cur
            events.append(("fact.confirmed", {"field": field, "fact_id": fact.id, "via": "repeat"}))
        elif same:
            fact = cur
        elif cur is None or is_correction:
            status = status_for_new()
            fact = _insert_fact(s, case, field, value, status, source, hedge=hedge, provenance=prov, proposed_by=actor,
                                supersedes=cur.id if cur else None, third_party=third_party,
                                matches_document=doc_match)
            if cur is not None:
                _supersede(existing_all, fact, "corrected by applicant")
                events.append(("fact.corrected", {"field": field, "old": cur.value, "new": value, "fact_id": fact.id,
                                                  "cause": "applicant_said_correction"}))
            else:
                events.append(("fact.recorded", {"field": field, "fact_id": fact.id, "status": status,
                                                 "hedge": hedge}))
        elif cur.source == "document" and _doc_quality(s, cur.provenance.get("document_id")) == "high":
            fact = _insert_fact(s, case, field, value, "disputed", source, hedge=hedge, provenance=prov,
                                proposed_by=actor, third_party=third_party,
                                note="conflicts with a high-quality document; document value will be read back")
            events.append(("fact.recorded", {"field": field, "fact_id": fact.id, "status": "disputed"}))
        else:
            # spoken vs spoken without a read-back: keep both, the field gets a read-back
            cur.status = "disputed"
            fact = _insert_fact(s, case, field, value, "proposed", source, hedge=hedge, provenance=prov,
                                proposed_by=actor, third_party=third_party, note=f"differs from earlier answer {cur.id}")
            events.append(("fact.recorded", {"field": field, "fact_id": fact.id, "status": "proposed",
                                             "conflict_with": cur.id}))

    for kind, payload in events:
        emit(s, case, kind, payload, actor_type, actor)
    if events:
        _mark_material(case, field)

    # (6) conflict rule → date_conflict flag; resolution on confirmation
    if fact is not None and fact.status == "confirmed":
        for fl in _open_flags(s, case, "date_conflict", field):
            resolve_flag(s, case, fl, "resolved by read-back")
            resolved.append(fl.id)
    elif fact is not None and doc_conflicts and catalog.is_date_field(field):
        fl = raise_flag(s, case, "date_conflict", layer=2, field=field,
                        detail={"documents": sorted({c["document_id"] for c in doc_conflicts if c["document_id"]})})
        if fl:
            new_flags.append(fl)

    # (7)(8) rules + layer 1/2 flags
    derived, rule_flags, rule_resolved = evaluate_rules(s, case)
    new_flags += rule_flags
    resolved += rule_resolved
    stopped = None
    if fact is not None and fact.id and (events or rb is not None):
        l1 = _layer1(s, case, field, value, utterance_text)
        if l1 and l1.get("stop"):
            stopped = l1["stop"]
        elif l1 and l1.get("flag"):
            new_flags.append(l1["flag"])
    if field.startswith("name") or field == "names.used":
        from .documents import check_names
        nf = check_names(s, case)
        new_flags += [f for f in nf if f is not None]
    after_fact_change(s, case)

    open_flags = [f for f in new_flags if f is not None]
    touching = [fl for fl in all_open_flags(s, case) if fl.field == field and fl.speed == FLAG_CONTINUE]
    flags_out = {fl.id: flag_dict(fl) for fl in touching + open_flags}
    ms = int((datetime.now() - t0).total_seconds() * 1000)
    resp = {
        "saved": True,
        "fact": fact_dict(fact) if fact else None,
        "spoken": spoken_value(field, fact.value) if fact else None,
        "flags": list(flags_out.values()),
        "resolved_flags": resolved,
        "derived": derived_summary(derived),
        "suggested_followups": followups(field, value, list(flags_out.values()), derived),
        "briefing_version": latest_briefing_version(s, case.id),
        "server_ms": ms,
    }
    if stopped:
        resp.update({"stopped": True, "script_key": "stop"})
    if fact and fact.status == "disputed":
        resp["note"] = "disputed"
    return resp


def _record_consent(s, case, value, utterance_id, session_id, third_party, actor_type, actor) -> dict[str, Any]:
    if value is True:
        f = _insert_fact(s, case, "consent", True, "confirmed", "spoken",
                         provenance={"utterance_id": utterance_id, "session_id": session_id,
                                     "disclosure_version": case.disclosure_version}, proposed_by=actor)
        _supersede([x for x in facts_for(s, case.id, "consent") if x.id != f.id], f)
        payload = {"disclosure_version": case.disclosure_version, "utterance_id": utterance_id}
        if third_party:
            sess = s.get(CallSession, session_id) if session_id else None
            payload.update({"third_party_present": True,
                            "relation": sess.third_party_relation if sess else None})
        emit(s, case, "consent.given", payload, actor_type, actor)
        if case.state == "consent_pending":
            set_state(s, case, "intake", "consent.given")
        evaluate_rules(s, case)
        after_fact_change(s, case)
        return {"saved": True, "fact": fact_dict(f), "flags": [], "resolved_flags": [], "derived": None,
                "suggested_followups": [], "briefing_version": latest_briefing_version(s, case.id)}
    emit(s, case, "consent.declined", {"disclosure_version": case.disclosure_version, "utterance_id": utterance_id},
         actor_type, actor)
    return {"saved": True, "fact": None, "consent": False, "script_key": "consent_declined", "flags": [],
            "resolved_flags": [], "derived": None, "suggested_followups": [],
            "briefing_version": latest_briefing_version(s, case.id)}


def followups(field: str, value: Any, flags: list[dict], derived: Derived | None) -> list[str]:
    out = []
    cats = {f["category"] for f in flags}
    if "citation" in cats and field.startswith("background."):
        out += ["date", "county", "paid or not"]
    if "absence_gt_180" in cats or "absence_gte_365" in cats:
        out += ["read back return date", "ask whether home was kept"]
    return out


# ---------------------------------------------------------------- secure entry & typed values

def secure_entry(s: Session, case: Case, field: str, value: Any, actor: str = "applicant",
                 actor_type: str = "applicant") -> dict[str, Any]:
    d = catalog.field_def(field)
    if d is None or "S" not in d.get("capture", "") and d.get("capture") != "P":
        raise CaseError("not_secure_field", "this field is not entered on screen", field)
    try:
        value = normalize(field, value)
    except ValueError_ as e:
        raise CaseError("invalid_value", str(e), field) from None
    existing = facts_for(s, case.id, field)
    masked = catalog.is_masked(field)
    stored = catalog.mask_token(field) if masked else value
    source = "applicant_typed" if actor_type == "applicant" else "staff_typed"
    f = _insert_fact(s, case, field, stored, "confirmed", source, proposed_by=actor,
                     provenance={"typed_by": actor}, supersedes=existing[-1].id if existing else None)
    _supersede(existing, f, "replaced by typed entry")
    if masked:
        sv = str(value)
        s.add(VaultValue(fact_id=f.id, clinic_id=case.clinic_id, case_id=case.id, field=field,
                         ciphertext=vault.encrypt(sv), last4=sv[-4:]))
    emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "status": "confirmed", "source": source,
                                    "masked": masked}, actor_type, actor)
    _mark_material(case, field)
    evaluate_rules(s, case)
    after_fact_change(s, case)
    return {"saved": True, "fact": fact_dict(f)}


def vault_lookup(s: Session, fact_id: str) -> str | None:
    v = s.get(VaultValue, fact_id)
    return vault.decrypt(v.ciphertext) if v else None


def vault_last4(s: Session, fact_id: str) -> str | None:
    v = s.get(VaultValue, fact_id)
    return v.last4 if v else None


def real_value(s: Session, case_id: str, field: str) -> Any:
    """Real value for the form filler (vault decrypted here and only here)."""
    f = current_facts(s, case_id).get(field)
    if f is None:
        return None
    if catalog.is_masked(field):
        return vault_lookup(s, f.id)
    return f.value


# ---------------------------------------------------------------- flags & review items

def all_open_flags(s: Session, case: Case) -> list[Flag]:
    return list(s.scalars(select(Flag).where(Flag.case_id == case.id, Flag.status == "open").order_by(Flag.ts)))


def _open_flags(s: Session, case: Case, category: str, field: str | None = None) -> list[Flag]:
    q = select(Flag).where(Flag.case_id == case.id, Flag.status == "open", Flag.category == category)
    if field is not None:
        q = q.where(Flag.field == field)
    return list(s.scalars(q))


def flag_dict(fl: Flag, applicant: bool = False) -> dict[str, Any]:
    if applicant and fl.speed == STOP_NOW:
        return {"id": fl.id, "speed": STOP_NOW}
    return {"id": fl.id, "category": fl.category, "speed": fl.speed, "layer": fl.layer, "field": fl.field,
            "status": fl.status, "rule_id": fl.rule_id, "label_es": fl.applicant_label_es}


def raise_flag(s: Session, case: Case, category: str, layer: int, field: str | None = None,
               rule_id: str | None = None, detail: dict | None = None, actor: str = "case_api",
               actor_type: str = "system", return_existing: bool = False) -> Flag | None:
    """Create a flag + review item, deduped on (category, field) while open. Stop categories route to stop_now."""
    info = cat_info(category)
    if info["speed"] == STOP_NOW:
        stop_now(s, case, category, layer=layer, field=field)
        return None
    existing = _open_flags(s, case, category, field)
    if not existing and (field is None or layer in (1, 4)) and category in ("citation", "taxes",
                                                                            "medical_exception_question"):
        # the keyword backstop and the official question describe the same thing: one item
        existing = _open_flags(s, case, category)
    if existing:
        if field and existing[0].field is None:
            existing[0].field = field  # the keyword hit and the official question are one item
            existing[0].section = catalog.section_of(field)
            for ri in s.scalars(select(ReviewItem).where(ReviewItem.flag_id == existing[0].id)):
                ri.field = field
        return existing[0] if return_existing else None
    summary = facts_summary(s, case, category, field)
    decided = s.scalars(select(ReviewItem).where(
        ReviewItem.case_id == case.id, ReviewItem.category == category, ReviewItem.status == "closed",
        ReviewItem.decision.is_not(None), ReviewItem.decision != "auto_resolved",
        ReviewItem.field == field if field is not None else ReviewItem.field.is_(None))).all()
    if any(r.facts_summary == summary for r in decided):
        return None  # a reviewer already decided this, and nothing behind it changed
    fl = Flag(clinic_id=case.clinic_id, case_id=case.id, category=category, speed=FLAG_CONTINUE, layer=layer,
              field=field, section=catalog.section_of(field) if field else None, rule_id=rule_id,
              detail=detail or {}, applicant_label_es=info.get("label_es"), ts=now())
    s.add(fl)
    s.flush()
    trigger = RULE_TRIGGERS.get(category) or {
        1: "Official question answered yes (layer 1)", 2: f"Rule {rule_id or category} (layer 2)",
        3: "Liaison flag (layer 3)", 4: "Keyword (layer 4)"}.get(layer, f"layer {layer}")
    ri = ReviewItem(clinic_id=case.clinic_id, case_id=case.id, flag_id=fl.id, category=category,
                    speed=FLAG_CONTINUE, field=field, blocking=info["blocks"], trigger=trigger,
                    facts_summary=summary, proposed_by=actor, ts=now())
    s.add(ri)
    s.flush()
    case.material_changed_at = now()
    emit(s, case, "flag.raised", {"flag_id": fl.id, "speed": FLAG_CONTINUE, "category": category, "field": field,
                                  "layer": layer, "review_item_id": ri.id}, actor_type, actor)
    if info.get("label_es") and category not in ("date_conflict", "document_conflict", "document_owner"):
        push(s, case, "referral_card", referral_card(s, case, fl))  # internal conflicts are settled by read-back
    return fl


def resolve_flag(s: Session, case: Case, fl: Flag, note: str) -> None:
    fl.status = "resolved"
    for ri in s.scalars(select(ReviewItem).where(ReviewItem.flag_id == fl.id, ReviewItem.status == "open")):
        ri.status = "closed"
        ri.decision = "auto_resolved"
        ri.decision_note = note
        ri.decided_at = now()
    emit(s, case, "flag.resolved", {"flag_id": fl.id, "category": fl.category, "field": fl.field, "note": note})


def facts_summary(s: Session, case: Case, category: str, field: str | None) -> str | None:
    vals = fact_values(s, case.id)
    m = catalog.LIST_RE.match(field or "")
    if category.startswith("absence") and m:
        i = m["i"]
        der = latest_derived(s, case.id)
        days = next((t["days"] for t in (der.data.get("trips", []) if der else []) if str(t["index"]) == i), None)
        return (f"Trip {int(i) + 1}: {vals.get(f'trips[{i}].departure')} → {vals.get(f'trips[{i}].return')}, "
                f"{days} days" + (f" (engine {der.id})" if der else ""))
    if field:
        v = vals.get(field)
        return f"{catalog.label_en(field)}: {v}" if v is not None else catalog.label_en(field)
    return None


def referral_card(s: Session, case: Case, fl: Flag) -> dict[str, Any]:
    from .clinic_service import clinic_phone, referral_overrides, reviewer_first_name
    # Clinic-settable override text (Settings > Referral card text) is Spanish-only for now -- shown as-is
    # when a clinic has set one, regardless of the applicant's language. The unoverridden defaults below are
    # fully bilingual.
    overrides = referral_overrides(s, case)
    lang = case_lang(case)
    if fl.speed == STOP_NOW:
        title = overrides.get("stop_now") or (
            "Your clinic will contact you about this" if lang == "en" else "Su clínica le va a contactar sobre esta parte")
        body = ("A licensed professional needs to review this before you file. Ellis can't advise you on it."
                if lang == "en" else
                "Esto debe revisarlo un profesional con licencia antes de presentar su solicitud. "
                "Ellis no puede aconsejarle sobre esto.")
        actions = ["Understood", "This wasn't about me"] if lang == "en" else ["Entendido", "Esto no era sobre mí"]
        return {"variant": "stop_now", "flag_id": fl.id, "title": title, "body": body,
                "who": reviewer_first_name(s, case), "phone": clinic_phone(s, case), "actions": actions,
                "show_emergency": bool(fl.detail.get("imminent"))}
    # Gap.label_es is the only stored label (no label_en column); the gap list stays Spanish even in an
    # English session, a smaller known gap than the card's own title/body/actions, which are fully bilingual.
    gaps = [g.label_es or g.reason for g in s.scalars(select(Gap).where(
        Gap.case_id == case.id, Gap.status == "open"))
        if fl.id in (g.key or "") or (fl.field and fl.field in (g.key or "")) or fl.category in (g.key or "")]
    title = overrides.get("flag_continue") or (
        "Someone at your clinic will review this" if lang == "en" else "Esto lo revisará una persona de su clínica")
    actions = ["Understood"] if lang == "en" else ["Entendido"]
    return {"variant": "flag_continue", "flag_id": fl.id, "title": title,
            "item": item_text(s, case, fl, lang), "prepare": gaps,
            "who": reviewer_first_name(s, case), "phone": clinic_phone(s, case), "actions": actions}


def item_text(s: Session, case: Case, fl: Flag, lang: str | None = None) -> str:
    from .flags import category as flag_category
    lang = lang or case_lang(case)
    cat_label = flag_category(fl.category).get(f"label_{lang}")
    default = "Question for your clinic" if lang == "en" else "Pregunta para su clínica"
    label = (cat_label or (fl.applicant_label_es if lang == "es" else None) or default)
    vals = fact_values(s, case.id)
    if fl.category == "citation":
        details = [str(v) for k, v in vals.items() if k.startswith("background.detail.citation")]
        return label + (", " + ", ".join(details) if details else "")
    m = catalog.LIST_RE.match(fl.field or "")
    if m and fl.category.startswith("absence"):
        trip_word = "trip" if lang == "en" else "viaje"
        return f"{label}: {trip_word} {int(m['i']) + 1}"
    return label


def stop_now(s: Session, case: Case, category: str, layer: int, field: str | None = None,
             session_id: str | None = None, actor: str = "liaison") -> dict[str, Any]:
    """Stores only {category, speed, layer, ts}; defers the related section; never the words."""
    section = catalog.section_for_category(category)
    existing = _open_flags(s, case, category)
    if existing:
        fl = existing[0]
        new = False
    else:
        fl = Flag(clinic_id=case.clinic_id, case_id=case.id, category=category, speed=STOP_NOW, layer=layer,
                  field=None, section=section, detail={}, ts=now())
        s.add(fl)
        s.flush()
        s.add(ReviewItem(clinic_id=case.clinic_id, case_id=case.id, flag_id=fl.id, category=category,
                         speed=STOP_NOW, blocking=True, resolution_required="professional_review",
                         trigger={1: "Official question answered yes (layer 1)", 3: "Liaison stop (layer 3)",
                                  4: "Keyword (layer 4)"}.get(layer, f"layer {layer}"), ts=now()))
        case.material_changed_at = now()
        # staff agents receive section only: no category, no time, no words
        emit(s, case, "flag.raised", {"flag_id": fl.id, "speed": STOP_NOW, "section": section}, "liaison", actor)
        new = True
    deferred = []
    group = section.split(".", 1)[1] if "." in section else None
    keys = catalog.group_fields(group) if group else []
    if field and field.startswith("background.") and field not in keys:
        keys.append(field)
    for k in keys:
        cur = current_facts(s, case.id).get(k)
        if cur is not None and cur.value == catalog.DEFERRED:
            continue
        others = facts_for(s, case.id, k)
        f = _insert_fact(s, case, k, catalog.DEFERRED, "confirmed", "derived", proposed_by="case_api",
                         provenance={"flag_id": fl.id}, note="deferred to licensed professional")
        _supersede(others, f)
        deferred.append(k)
    if deferred:
        emit(s, case, "section.deferred", {"section": section, "fields": deferred})
    push(s, case, "referral_card", referral_card(s, case, fl))
    after_fact_change(s, case)
    return {"flag_id": fl.id, "speed": STOP_NOW, "script_key": "stop", "new_flag": new, "deferred": deferred}


def _deferred_fields(s: Session, case: Case) -> set[str]:
    return {k for k, v in cur_view(s, case.id).items() if v["value"] == catalog.DEFERRED}


def deferred_sections(s: Session, case: Case) -> set[str]:
    return {fl.section for fl in s.scalars(select(Flag).where(Flag.case_id == case.id, Flag.speed == STOP_NOW))
            if fl.section}


def flag_for_review(s: Session, case: Case, category: str, field: str | None = None,
                    actor: str = "liaison") -> dict[str, Any]:
    """Layer 3: the liaison raises a flag. Stop-list categories always route to the stop path."""
    if cat_info(category)["speed"] == STOP_NOW:
        res = stop_now(s, case, category, layer=3, field=field, actor=actor)
        return {"flag_id": res["flag_id"], "speed": STOP_NOW, "script_key": "stop"}
    cat = category if category in CATEGORIES else "liaison_note"
    fl = raise_flag(s, case, cat, layer=3, field=field, actor=actor, actor_type="liaison")
    if fl is None:
        fl = _open_flags(s, case, cat, field)[0]
    return {"flag_id": fl.id, "speed": fl.speed}


def _layer1(s: Session, case: Case, field: str, value: Any, utterance_text: str | None) -> dict | None:
    """Form-driven flags: official background / oath answers."""
    if field.startswith("background.") and field.count(".") == 1:
        q = catalog.background_question(field)
        if q is None:
            return None
        trigger_yes = value in ("yes", "not_sure")
        if "on_no" in q:
            if value in ("no", "not_sure"):
                return {"flag": raise_flag(s, case, q.get("category", "liaison_note"), layer=1, field=field)}
            return None
        if not trigger_yes:
            return None
        on_yes = q.get("on_yes", "stop_now")
        if on_yes == "classify":
            hit = keywords.stop_hit(utterance_text or "")
            if hit:
                stop_now(s, case, hit, layer=1, field=field)
                return {"stop": hit}
            return {"flag": raise_flag(s, case, "citation", layer=1, field=field, return_existing=True)}
        if on_yes == "flag_continue":
            return {"flag": raise_flag(s, case, q.get("category", "liaison_note"), layer=1, field=field,
                                       return_existing=True)}
        stop_now(s, case, q.get("category", "arrest"), layer=1, field=field)
        return {"stop": q.get("category", "arrest")}
    if field.startswith("oath.") and value in ("no", "not_sure"):
        return {"flag": raise_flag(s, case, "oath_answer", layer=1, field=field)}
    return None


# ---------------------------------------------------------------- derived / rules

def latest_derived(s: Session, case_id: str) -> Derived | None:
    return s.scalars(select(Derived).where(Derived.case_id == case_id).order_by(Derived.ts.desc(), Derived.id.desc())
                     .limit(1)).first()


def evaluate_rules(s: Session, case: Case) -> tuple[Derived | None, list[Flag], list[str]]:
    view = cur_view(s, case.id)
    values = {k: v["value"] for k, v in view.items() if v["value"] != catalog.DEFERRED
              and not catalog.is_masked(k)}
    low = {k for k, v in view.items() if v.get("hedge") or (isinstance(v["value"], str) and len(v["value"]) == 7
                                                            and catalog.is_date_field(k))}
    try:
        out = rules.evaluate(values, today(), rule_config(), fee_config(), low_confidence_fields=low)
    except Exception as e:  # rules unavailable: never speak a number from the LLM
        return None, [], [str(e)]
    prev = latest_derived(s, case.id)
    if prev is not None and prev.inputs_hash == out["inputs_hash"] and prev.rule_config_version == out["rule_config_version"]:
        der = prev
    else:
        der = Derived(clinic_id=case.clinic_id, case_id=case.id, data=out, rule_config_version=out["rule_config_version"],
                      inputs_hash=out["inputs_hash"], ts=now())
        s.add(der)
        s.flush()
        emit(s, case, "derived.computed", {"derived_id": der.id, "rule_config_version": der.rule_config_version,
                                           "error": out.get("error")})
    # eligibility_basis is derived (Phase 1: 5-year path only)
    if out.get("path") and view.get("eligibility_basis", {}).get("value") != out["path"]:
        others = facts_for(s, case.id, "eligibility_basis")
        f = _insert_fact(s, case, "eligibility_basis", out["path"], "confirmed", "derived", proposed_by="rules_engine",
                         provenance={"rule_run_id": der.id})
        _supersede(others, f)
    # layer-2 rule flags: sync with this run
    desired = {}
    for fl in out.get("flags", []):
        fld = f"trips[{fl['trip_index']}].return" if "trip_index" in fl else None
        desired[(fl["category"], fld)] = fl
    created, resolved = [], []
    for fl in s.scalars(select(Flag).where(Flag.case_id == case.id, Flag.status == "open", Flag.layer == 2,
                                           Flag.rule_id.is_not(None))):
        if (fl.category, fl.field) not in desired:
            resolve_flag(s, case, fl, "rule no longer applies after correction")
            resolved.append(fl.id)
    for (catg, fld), fl in desired.items():
        if catg not in CATEGORIES or catg == "trip_open":  # an unanswered return date is a queue item, not a flag
            continue
        new = raise_flag(s, case, catg, layer=2, field=fld, rule_id=fl["rule_id"], detail={"days": fl.get("days")})
        if new is not None:
            created.append(new)
        else:
            for ex in _open_flags(s, case, catg, fld):
                det = dict(ex.detail)
                det["days"] = fl.get("days")
                ex.detail = det
                for ri in s.scalars(select(ReviewItem).where(ReviewItem.flag_id == ex.id)):
                    ri.facts_summary = facts_summary(s, case, catg, fld)
    if out.get("error"):
        emit(s, case, "rules.validation_error", out["error"])
    return der, created, resolved


def derived_summary(der: Derived | None) -> dict[str, Any] | None:
    if der is None:
        return None
    d = der.data
    keys = ["trip_days", "presence_days", "as_of", "earliest_filing", "anniversary", "window_open", "path",
            "rule_config_version", "civics_version", "exemptions", "low_confidence", "error", "fee"]
    out = {k: d[k] for k in keys if k in d}
    out["derived_id"] = der.id
    if "earliest_filing" in d:
        early = date.fromisoformat(d["earliest_filing"])
        out["earliest_filing_spoken"] = rules.spoken_date_es(early)
        out["earliest_filing_spoken_en"] = rules.spoken_date_en(early)
    if "explain" in d:
        out["explain"] = d["explain"]
    return out


# ---------------------------------------------------------------- state machine & gate

STAGES = {"consent_pending": 0, "intake": 2, "evidence": 3, "review": 4, "ready": 4, "signed": 4,
          "referred_out": 4, "closed": 4}


def set_state(s: Session, case: Case, to: str, reason: str, actor_type: str = "system", actor: str = "case_api") -> None:
    if case.state == to:
        return
    frm = case.state
    case.state = to
    emit(s, case, "case.state_changed", {"from": frm, "to": to, "reason": reason}, actor_type, actor)


def open_gaps(s: Session, case_id: str) -> list[Gap]:
    return list(s.scalars(select(Gap).where(Gap.case_id == case_id, Gap.status == "open")))


def after_fact_change(s: Session, case: Case) -> None:
    """Re-evaluate the state machine after any write."""
    if case.state == "signed":
        so = s.scalars(select(Signoff).where(Signoff.case_id == case.id, Signoff.valid.is_(True))).first()
        if so is not None and facts_hash(s, case.id)[1] != so.facts_hash:
            so.valid = False
            for p in s.scalars(select(Packet).where(Packet.case_id == case.id, Packet.status == "current")):
                p.status = "stale"
            emit(s, case, "signoff.invalidated", {"signoff_id": so.id, "reason": "fact changed after sign-off"})
            set_state(s, case, "review", "fact changed after sign-off")
        return
    if case.state == "ready":
        if case.material_changed_at and case.signed_at is None:
            ready_ev = s.scalars(select(Event).where(Event.case_id == case.id, Event.kind == "case.state_changed")
                                 .order_by(Event.id.desc()).limit(1)).first()
            if ready_ev and _aware(case.material_changed_at) > _aware(ready_ev.ts):
                set_state(s, case, "review", "new material fact")
        return
    if case.state not in ("intake", "evidence", "review"):
        return
    der = latest_derived(s, case.id)
    view = cur_view(s, case.id)
    missing = catalog.missing_required(view, der.data if der else None, today(), confirmed=False)
    if missing:
        target = "intake"
    elif open_gaps(s, case.id):
        target = "evidence"
    else:
        target = "review"
    if target != case.state:
        set_state(s, case, target, {"intake": "required fields missing", "evidence": "all required fields have a fact",
                                    "review": "gap list empty"}[target])


def gate_status(s: Session, case: Case) -> dict[str, Any]:
    failing = []
    der = latest_derived(s, case.id)
    view = cur_view(s, case.id)
    missing = catalog.missing_required(view, der.data if der else None, today(), confirmed=True)
    if missing:
        failing.append({"code": "unconfirmed_fields", "message": f"{len(missing)} required fields are not confirmed",
                        "fields": missing[:50]})
    blocking = list(s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.blocking.is_(True),
                                                       ReviewItem.status.in_(["open", "case_blocked"]))))
    if blocking:
        failing.append({"code": "blocking_review_items", "message": f"{len(blocking)} blocking review items are open",
                        "items": [r.id for r in blocking]})
    qa = s.scalars(select(Memo).where(Memo.case_id == case.id, Memo.kind == "qa").order_by(Memo.ts.desc()).limit(1)).first()
    if qa is None:
        failing.append({"code": "qa_memo_missing", "message": "no QA memo yet"})
    elif case.material_changed_at and _aware(qa.ts) < _aware(case.material_changed_at):
        failing.append({"code": "qa_memo_stale", "message": "QA memo is older than the latest material change"})
    if der is None or der.rule_config_version != rule_config().version:
        failing.append({"code": "derived_stale", "message": "derived values not computed with the current rule config"})
    if der is not None and der.data.get("error"):
        failing.append({"code": "rules_validation_error", "message": der.data["error"]["message"],
                        "field": der.data["error"]["field"]})
    extracting = s.scalars(select(Document).where(Document.case_id == case.id, Document.status == "extracting")).first()
    if extracting:
        failing.append({"code": "document_extracting", "message": "a document is still being read"})
    return {"passes": not failing, "failing": failing}


def facts_hash(s: Session, case_id: str) -> tuple[list[str], str]:
    cur = current_facts(s, case_id)
    ids = sorted(f.id for f in cur.values())
    blob = json.dumps({k: [f.id, f.value] for k, f in sorted(cur.items())}, sort_keys=True, default=str)
    return ids, hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------- briefing

def latest_briefing(s: Session, case_id: str) -> Briefing | None:
    return s.scalars(select(Briefing).where(Briefing.case_id == case_id).order_by(Briefing.version.desc()).limit(1)).first()


def latest_briefing_version(s: Session, case_id: str) -> int:
    b = latest_briefing(s, case_id)
    return b.version if b else 0


def publish_briefing(s: Session, case: Case, body: dict[str, Any], proposed_by: str,
                     based_on_event_id: int | None = None) -> Briefing:
    """Assigns a monotonic version; rejects queue items naming stop-now-deferred fields and long tone hints."""
    deferred = _deferred_fields(s, case)
    dsections = deferred_sections(s, case)
    queue = []
    for it in body.get("queue", []):
        f = it.get("field")
        if f and (f in deferred or any(f.startswith(x) for x in dsections)):
            emit(s, case, "proposal.rejected", {"agent": proposed_by, "reason": "names a deferred field", "field": f},
                 "agent", proposed_by)
            continue
        queue.append(it)
    tone = body.get("tone_hint")
    if tone and len(tone) > 80:
        raise CaseError("tone_hint_too_long", "tone_hint over 80 characters")
    prev = latest_briefing(s, case.id)
    version = (prev.version if prev else 0) + 1
    clean = {
        "case": case.id, "version": version, "supersedes": prev.version if prev else None,
        "queue": queue, "tone_hint": tone,
        "applicant_visible_flags": body.get("applicant_visible_flags", []),
        "reviewer_notes_for_applicant": body.get("reviewer_notes_for_applicant", []),
        "do_not_mention": body.get("do_not_mention", []),
        "session_close": body.get("session_close"),
        "based_on_event_id": based_on_event_id,
    }
    b = Briefing(clinic_id=case.clinic_id, case_id=case.id, version=version, body=clean, proposed_by=proposed_by,
                 ts=now())
    s.add(b)
    s.flush()
    emit(s, case, "briefing.published", {"version": version}, "agent", proposed_by)
    return b


def pending_item(view: dict[str, dict], item: dict[str, Any]) -> bool:
    """Is a briefing queue item still worth doing given current facts?"""
    f = item.get("field")
    kind = item.get("kind")
    if kind == "ask" and f:
        return f not in view
    if kind == "read_back" and f:
        v = view.get(f)
        return v is not None and catalog.needs_confirmation(f, v)
    if kind == "request_secure_entry" and f:
        return f not in view
    return True


def get_briefing(s: Session, case: Case) -> dict[str, Any]:
    b = latest_briefing(s, case.id)
    view = cur_view(s, case.id)
    der = latest_derived(s, case.id)
    body = dict(b.body) if b else {"version": 0, "queue": []}
    body["queue"] = [it for it in body.get("queue", []) if pending_item(view, it)]
    body["fallback"] = catalog.fallback_queue(view, der.data if der else None, today(), deferred_sections(s, case))
    body["stale"] = b is None or (now() - _aware(b.ts)).total_seconds() > 60 and _aware(b.ts) < _aware(case.last_event_at)
    body["case_state"] = case.state
    body["patient_mode"] = bool((case.settings or {}).get("patient_mode"))
    body["first_name"] = case.first_name
    return body


def liaison_briefing(s: Session, case: Case) -> dict[str, Any]:
    """get_briefing plus what the liaison needs between turns. Masked fields only ever appear as tokens."""
    from . import views
    body = get_briefing(s, case)
    body["progress"] = views.section_progress(s, case)
    body["consent_given"] = consent_given(s, case)
    body["derived"] = derived_summary(latest_derived(s, case.id))
    body["gaps"] = [g.label_es or g.reason for g in open_gaps(s, case.id)]
    body["facts"] = {k: (catalog.mask_token(k) if catalog.is_masked(k) else v["value"])
                     for k, v in cur_view(s, case.id).items()}
    return body
