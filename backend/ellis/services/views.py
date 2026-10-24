"""Read models for the applicant client and the clinic workspace."""

from __future__ import annotations

import re

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import (
    Briefing, Case, CaseLink, Clinic, Derived, Document, Event, Extraction, Fact, Flag, Gap, Memo, Packet, ReviewItem,
    StaffUser, Task, Utterance,
)
from . import auth, case_service as cs, catalog
from .flags import STOP_NOW
from .values import display_value

AGENT_LABELS_ES = {"case_manager": "Coordinador del caso", "doc_paralegal": "Revisor de documentos",
                   "docketing_clerk": "Control de fechas", "qa_reviewer": "Control de calidad"}
AGENT_LABELS_EN = {"case_manager": "Case coordinator", "doc_paralegal": "Document checker",
                   "docketing_clerk": "Deadline tracker", "qa_reviewer": "Quality check"}
ROADMAP_ES = [
    {"key": "inicio", "label": "Inicio"}, {"key": "elegibilidad", "label": "Elegibilidad"},
    {"key": "entrevista", "label": "Entrevista"}, {"key": "documentos", "label": "Documentos"},
    {"key": "revision", "label": "Revisión y firma"},
]
ROADMAP_EN = [
    {"key": "inicio", "label": "Start"}, {"key": "elegibilidad", "label": "Eligibility"},
    {"key": "entrevista", "label": "Interview"}, {"key": "documentos", "label": "Documents"},
    {"key": "revision", "label": "Review and sign"},
]
FUTURE_ES = ["Presentar la solicitud", "Huellas (biometría)", "Estudio: cívica e inglés", "Entrevista de práctica",
             "Entrevista", "Ceremonia de juramento"]
FUTURE_EN = ["File the application", "Biometrics (fingerprints)", "Civics and English study", "Mock interview",
             "Interview", "Oath ceremony"]
STAGE_NAMES = {"consent_pending": "Consent", "intake": "Intake", "evidence": "Evidence", "review": "Review",
               "ready": "Ready for sign-off", "signed": "Signed", "referred_out": "Referred out", "closed": "Closed"}


def roadmap_index(s: Session, case: Case) -> int:
    if case.state == "consent_pending":
        return 0
    if case.state == "intake":
        lpr = cs.current_facts(s, case.id).get("lpr_since")
        return 1 if lpr is None or lpr.status != "confirmed" else 2
    if case.state == "evidence":
        return 3
    return 4


CHIP_LABELS = {
    "review": {"es": "Para revisión", "en": "For review"},
    "corrected": {"es": "Corregido", "en": "Corrected"},
    "deferred": {"es": "Con su profesional", "en": "With your professional"},
    "confirmed": {"es": "Confirmado ✓", "en": "Confirmed ✓"},
    "document": {"es": "De su documento", "en": "From your document"},
    "spoken": {"es": "Usted lo dijo", "en": "You said it"},
}


def chip(f: dict, open_fields: set[str], corrected: bool, lang: str = "es") -> dict[str, str]:
    if f["field"] in open_fields:
        key = "review"
    elif corrected:
        key = "corrected"
    elif f["value_raw"] == catalog.DEFERRED:
        key = "deferred"
    elif f["status"] == "confirmed":
        key = "confirmed"
    elif f["source"] == "document":
        key = "document"
    else:
        key = "spoken"
    return {"key": key, "label": CHIP_LABELS[key][lang]}


def applicant_value(s: Session, key: str, f: Fact, lang: str = "es") -> str:
    from datetime import date as _date
    from ..rules.engine import MONTHS_EN, MONTHS_ES, short_date_en, short_date_es
    if catalog.is_date_field(key) and isinstance(f.value, str) and f.value != catalog.DEFERRED:
        if f.value == "present":
            return "to present" if lang == "en" else "hasta hoy"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.value):
            return short_date_en(_date.fromisoformat(f.value)) if lang == "en" else short_date_es(_date.fromisoformat(f.value))
        if re.fullmatch(r"\d{4}-\d{2}", f.value):
            months = MONTHS_EN if lang == "en" else MONTHS_ES
            return f"{months[int(f.value[5:7]) - 1]} {f.value[:4]}" if lang == "en" \
                else f"{months[int(f.value[5:7]) - 1]} de {f.value[:4]}"
    if catalog.is_masked(key):
        last4 = cs.vault_last4(s, f.id)
        return f"•••• {last4}" if last4 else "••••"
    if f.value == catalog.DEFERRED:
        return "To complete with your professional" if lang == "en" else "Para completar con su profesional"
    return cs.spoken_value(key, f.value, lang=lang) if catalog.is_date_field(key) or isinstance(f.value, (bool, list)) \
        or f.value in ("yes", "no", "not_sure") or (catalog.field_def(key) or {}).get("type") == "enum" else str(f.value)


def facts_panel(s: Session, case: Case) -> list[dict[str, Any]]:
    lang = cs.case_lang(case)
    label_of = catalog.label_en if lang == "en" else catalog.label_es
    cur = cs.current_facts(s, case.id)
    open_fields = {fl.field for fl in cs.all_open_flags(s, case) if fl.field and fl.speed != STOP_NOW}
    all_f = {f.id: f for f in cs.facts_for(s, case.id, include_superseded=True)}
    der = cs.latest_derived(s, case.id)
    trip_days = {t["index"]: t["days"] for t in (der.data.get("trips", []) if der else [])}
    groups: dict[str, list] = {}
    for key, f in cur.items():
        if key in ("consent", "eligibility_basis") or key.endswith(".another"):
            continue
        prev = all_f.get(f.supersedes) if f.supersedes else None
        corrected = prev is not None and prev.value != f.value and prev.source != "document" and f.source == "spoken"
        item = {"field": key, "label": label_of(key), "value": applicant_value(s, key, f, lang), "status": f.status,
                "source": f.source, "hedge": f.hedge, "value_raw": f.value, "ts": f.ts.isoformat(),
                "simulated": bool(f.provenance.get("simulated"))}
        if corrected:
            item["corrected_from"] = applicant_value(s, key, prev, lang)
        m = catalog.LIST_RE.match(key)
        if m and m["list"] == "trips" and m["sub"] == "return" and int(m["i"]) in trip_days:
            item["days"] = trip_days[int(m["i"])]
            if corrected and prev is not None and prev.value:
                from datetime import date
                dep = cur.get(f"trips[{m['i']}].departure")
                if dep:
                    try:
                        item["days_from"] = (date.fromisoformat(prev.value) - date.fromisoformat(dep.value)).days
                    except (TypeError, ValueError):
                        pass
        item["chip"] = chip(item, open_fields, corrected, lang)
        del item["value_raw"]
        groups.setdefault(catalog.section_of(key), []).append(item)
    out = []
    for sec in catalog.sections():
        items = groups.get(sec["key"])
        if items:
            items.sort(key=lambda i: _key_order(i["field"]))
            sec_label = sec.get("label_en") if lang == "en" else sec["label_es"]
            out.append({"section": sec["key"], "label": sec_label or sec["label_es"], "items": items})
    return out


def _key_order(k: str):
    m = catalog.LIST_RE.match(k)
    return (m["list"], int(m["i"]), k) if m else ("", 0, k)


def section_progress(s: Session, case: Case) -> list[dict[str, Any]]:
    lang = cs.case_lang(case)
    der = cs.latest_derived(s, case.id)
    view = cs.cur_view(s, case.id)
    req = catalog.required_fields(view, der.data if der else None, cs.today())
    out = []
    for sec in catalog.sections():
        keys = [k for k in req if catalog.section_of(k) == sec["key"]]
        if not keys:
            continue
        have = [k for k in keys if k in view]
        conf = [k for k in keys if view.get(k, {}).get("status") == "confirmed"]
        deferred = [k for k in keys if view.get(k, {}).get("value") == catalog.DEFERRED]
        state = ("blocked" if deferred else "done" if len(conf) == len(keys)
                 else "partial" if have else "not_started")
        label = sec.get("label_en") if lang == "en" else sec["label_es"]
        out.append({"section": sec["key"], "label": label or sec["label_es"], "state": state,
                    "done": len(conf), "total": len(keys)})
    return out


def team_cards(s: Session, case: Case, limit: int = 8) -> list[dict[str, Any]]:
    lang = cs.case_lang(case)
    labels, default = (AGENT_LABELS_EN, "Your team") if lang == "en" else (AGENT_LABELS_ES, "Su equipo")
    tasks = list(s.scalars(select(Task).where(Task.case_id == case.id, Task.title_es.is_not(None))
                           .order_by(Task.ts.desc()).limit(limit)))
    return [{"id": t.id, "agent": t.agent, "label": labels.get(t.agent, default), "text": t.title_es,
             "ts": t.ts.isoformat(), "status": t.status} for t in tasks]


def referral_cards(s: Session, case: Case) -> list[dict[str, Any]]:
    cards = []
    for fl in cs.all_open_flags(s, case):
        if fl.speed == STOP_NOW or (fl.applicant_label_es and fl.category not in ("date_conflict", "document_conflict",
                                                                                 "document_owner")):
            cards.append(cs.referral_card(s, case, fl))
    return cards


def applicant_case(s: Session, case: Case) -> dict[str, Any]:
    clinic = s.get(Clinic, case.clinic_id)
    open_items = s.scalar(select(func.count()).select_from(ReviewItem).where(
        ReviewItem.case_id == case.id, ReviewItem.status == "open")) or 0
    gaps = [{"id": g.id, "document_type": g.document_type, "label": g.label_es or g.reason}
            for g in s.scalars(select(Gap).where(Gap.case_id == case.id, Gap.status == "open"))]
    docs = [{"id": d.id, "document_type": d.document_type, "status": d.status, "quality": d.quality,
             "filename": d.filename, "ts": d.ts.isoformat()}
            for d in s.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.ts))]
    notes = [{"id": r.id, "note": r.decision_note, "label": (s.get(Flag, r.flag_id).applicant_label_es
                                                              if r.flag_id and s.get(Flag, r.flag_id) else None)}
             for r in s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id,
                                                         ReviewItem.decision == "clear_with_referral"))]
    blocked = s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id,
                                                 ReviewItem.status == "case_blocked")).first() is not None
    der = cs.latest_derived(s, case.id)
    filing = None
    if der and der.data.get("earliest_filing"):
        filing = {"earliest_filing": der.data["earliest_filing"], "window_open": der.data.get("window_open"),
                  "rule_config_version": der.rule_config_version}
    b = cs.latest_briefing(s, case.id)
    return {
        "case_id": case.id, "first_name": case.first_name, "state": case.state, "sub_mode": case.sub_mode,
        "language": case.language,
        "clinic": {"name": clinic.name, "phone": (clinic.settings or {}).get("phone"), "is_demo": clinic.is_demo},
        "patient_mode": bool((case.settings or {}).get("patient_mode")),
        "facts": facts_panel(s, case), "progress": section_progress(s, case), "team": team_cards(s, case),
        "referrals": referral_cards(s, case), "open_review_items": open_items, "gaps": gaps, "documents": docs,
        "reviewer_notes": notes, "case_blocked": blocked, "filing_window": filing,
        "roadmap": {"stages": ROADMAP_EN if case.language.split("-")[0] == "en" else ROADMAP_ES,
                   "current": roadmap_index(s, case),
                   "future": FUTURE_EN if case.language.split("-")[0] == "en" else FUTURE_ES},
        "briefing_version": b.version if b else 0,
        "packet_ready": s.scalars(select(Packet).where(Packet.case_id == case.id, Packet.status == "current")).first()
        is not None,
    }


# ---------------------------------------------------------------- clinic

def progress_ratio(s: Session, case: Case) -> tuple[int, int]:
    der = cs.latest_derived(s, case.id)
    view = cs.cur_view(s, case.id)
    req = catalog.required_fields(view, der.data if der else None, cs.today())
    return sum(1 for k in req if k in view), len(req)


def case_row(s: Session, case: Case) -> dict[str, Any]:
    have, total = progress_ratio(s, case)
    blocking = list(s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.status == "open",
                                                       ReviewItem.blocking.is_(True))))
    link = s.scalars(select(CaseLink).where(CaseLink.case_id == case.id).order_by(CaseLink.issued_at.desc())).first()
    reviewer = s.get(StaffUser, case.assigned_reviewer) if case.assigned_reviewer else None
    return {
        "id": case.id, "applicant": case.display_name, "full_name": f"{case.first_name} {case.last_name}",
        "state": case.state, "stage": STAGE_NAMES.get(case.state, case.state),
        "progress": {"have": have, "total": total},
        "open_blocking": len(blocking), "has_stop_now": any(r.speed == STOP_NOW for r in blocking),
        "assigned_reviewer": {"id": reviewer.id, "name": reviewer.name} if reviewer else None,
        "last_activity": case.last_event_at.isoformat() if case.last_event_at else None,
        "link_status": auth.link_status(link),
        "patient_mode": bool((case.settings or {}).get("patient_mode")),
    }


def fact_history(s: Session, case: Case) -> list[dict[str, Any]]:
    by: dict[str, list[Fact]] = {}
    for f in cs.facts_for(s, case.id, include_superseded=True):
        by.setdefault(f.field, []).append(f)
    req = set(catalog.required_fields(cs.cur_view(s, case.id), None, cs.today()))
    open_fields = {fl.field for fl in cs.all_open_flags(s, case) if fl.field}
    rows = []
    for key in sorted(by, key=lambda k: (_section_index(k), _key_order(k))):
        fs = by[key]
        cur = [f for f in fs if f.status != "superseded"]
        current = ([f for f in cur if f.status != "disputed"] or cur or fs)[-1]
        rows.append({
            "field": key, "label": catalog.label_en(key), "section": catalog.section_of(key),
            "required": key in req, "masked": catalog.is_masked(key), "for_review": key in open_fields,
            "current": _fact_row(s, current),
            "history": [_fact_row(s, f) for f in reversed(fs) if f.id != current.id],
        })
    return rows


def _section_index(k: str) -> int:
    sec = catalog.section_of(k)
    for i, s_ in enumerate(catalog.sections()):
        if s_["key"] == sec:
            return i
    return 99


def _fact_row(s: Session, f: Fact) -> dict[str, Any]:
    if catalog.is_masked(f.field):
        last4 = cs.vault_last4(s, f.id)
        value = f"•••• {last4}" if last4 else f.value
    else:
        value = display_value(f.field, f.value)
    prov = dict(f.provenance)
    desc = f.source
    if f.source == "document":
        desc = f"document {prov.get('document_type', '')} ({prov.get('document_id', '')})"
    elif f.source == "spoken":
        desc = f"spoken{', session ' + prov['session_id'] if prov.get('session_id') else ''}, {f.ts.strftime('%b %d %H:%M')}"
    if prov.get("simulated"):
        desc += " · simulated"
    return {"id": f.id, "value": value, "status": f.status, "source": f.source, "hedge": f.hedge,
            "provenance": desc, "proposed_by": f.proposed_by, "note": f.note, "ts": f.ts.isoformat(),
            "matches_document": f.matches_document, "third_party": f.third_party}


def clinic_case_detail(s: Session, case: Case, staff: StaffUser) -> dict[str, Any]:
    clinic = s.get(Clinic, case.clinic_id)
    docs = []
    for d in s.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.ts)):
        x = s.scalars(select(Extraction).where(Extraction.document_id == d.id).order_by(Extraction.ts.desc())).first()
        docs.append({"id": d.id, "document_type": d.document_type, "filename": d.filename, "status": d.status,
                     "quality": d.quality, "checks": d.checks, "exhibit": d.exhibit, "ts": d.ts.isoformat(),
                     "uploaded_by": d.uploaded_by, "extraction": x.data if x else None,
                     "extractor": x.extractor if x else None})
    events = [{"id": e.id, "kind": e.kind, "payload": e.payload, "actor_type": e.actor_type, "actor": e.actor,
               "ts": e.ts.isoformat()}
              for e in s.scalars(select(Event).where(Event.case_id == case.id).order_by(Event.id.desc()).limit(400))]
    memos = [{"id": m.id, "kind": m.kind, "body_md": m.body_md, "proposed_by": m.proposed_by, "ts": m.ts.isoformat()}
             for m in s.scalars(select(Memo).where(Memo.case_id == case.id).order_by(Memo.ts.desc()))]
    retention = (clinic.settings or {}).get("retention", {})
    transcript = None
    if retention.get("transcripts_days") != "none":
        transcript = [{"id": u.id, "session_id": u.session_id, "speaker": u.speaker, "text": u.text,
                       "redacted": u.redacted, "locked": u.locked, "ts": u.ts.isoformat()}
                      for u in s.scalars(select(Utterance).where(Utterance.case_id == case.id).order_by(Utterance.ts))]
    tasks = [{"id": t.id, "agent": t.agent, "agent_label": AGENT_LABELS_EN.get(t.agent, t.agent), "kind": t.kind,
              "title": t.title, "status": t.status, "field": t.field, "ts": t.ts.isoformat()}
             for t in s.scalars(select(Task).where(Task.case_id == case.id).order_by(Task.ts.desc()).limit(100))]
    gaps = [{"id": g.id, "document_type": g.document_type, "reason": g.reason, "status": g.status}
            for g in s.scalars(select(Gap).where(Gap.case_id == case.id).order_by(Gap.ts))]
    items = [review_item_view(s, r, staff) for r in s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id)
                                                              .order_by(ReviewItem.ts))]
    der = cs.latest_derived(s, case.id)
    b = cs.latest_briefing(s, case.id)
    packets = [{"id": p.id, "kind": p.kind, "filename": p.filename, "status": p.status, "sha256": p.sha256,
                "ts": p.ts.isoformat()}
               for p in s.scalars(select(Packet).where(Packet.case_id == case.id).order_by(Packet.ts.desc()))]
    return {
        "case": case_row(s, case), "clinic": {"name": clinic.name, "is_demo": clinic.is_demo},
        "settings": case.settings, "gate": cs.gate_status(s, case), "facts": fact_history(s, case),
        "documents": docs, "events": events, "memos": memos, "transcript": transcript, "tasks": tasks,
        "gaps": gaps, "review_items": items, "derived": der.data if der else None,
        "briefing": b.body if b else None, "packets": packets,
    }


def review_item_view(s: Session, r: ReviewItem, staff: StaffUser | None) -> dict[str, Any]:
    case = s.get(Case, r.case_id)
    fl = s.get(Flag, r.flag_id) if r.flag_id else None
    evidence = []
    for did in r.evidence or []:
        d = s.get(Document, did)
        if d:
            evidence.append({"id": d.id, "document_type": d.document_type, "filename": d.filename})
    base = {"id": r.id, "case_id": r.case_id, "applicant": case.display_name, "category": r.category,
            "speed": r.speed, "blocking": r.blocking, "status": r.status, "ts": r.ts.isoformat(),
            "decision": r.decision, "decision_note": r.decision_note, "decided_at":
                r.decided_at.isoformat() if r.decided_at else None,
            "self_report": bool(fl and fl.applicant_self_report)}
    if r.speed == STOP_NOW:
        # category and timestamp only
        base.update({"banner": "Contact the applicant directly. Ellis recorded no details.",
                     "trigger": r.trigger, "resolution_required": r.resolution_required})
        return base
    base.update({"field": r.field, "trigger": r.trigger, "facts": r.facts_summary, "evidence": evidence,
                 "agent_notes": r.agent_notes, "rule_id": fl.rule_id if fl else None,
                 "layer": fl.layer if fl else None})
    return base
