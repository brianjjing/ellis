"""Read models for the applicant client and the clinic workspace."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import (
    Briefing, Case, CaseLink, Clinic, Deadline, Derived, Document, Event, Extraction, Fact, Flag, Gap, Memo, Packet, ReviewItem,
    StaffUser, Task, Utterance,
)
from ..extraction.schemas import LABELS_EN
from . import activity, auth, case_service as cs, catalog, languages
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


def roadmap_index(case: Case, progress: list[dict[str, Any]]) -> int:
    if case.state == "consent_pending":
        return 0
    if any(p["state"] != "done" for p in progress):
        return 1  # the interview stage, and everything after it, waits until every part of the form is done
    return {"intake": 2, "evidence": 3}.get(case.state, 4)


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
    progress = section_progress(s, case)
    return {
        "case_id": case.id, "first_name": case.first_name, "state": case.state, "sub_mode": case.sub_mode,
        "language": case.language,
        "clinic": {"name": clinic.name, "phone": (clinic.settings or {}).get("phone"), "is_demo": clinic.is_demo},
        "patient_mode": bool((case.settings or {}).get("patient_mode")),
        "facts": facts_panel(s, case), "progress": progress, "team": team_cards(s, case),
        "referrals": referral_cards(s, case), "open_review_items": open_items, "gaps": gaps, "documents": docs,
        "reviewer_notes": notes, "case_blocked": blocked, "filing_window": filing,
        "roadmap": {"stages": ROADMAP_EN if case.language.split("-")[0] == "en" else ROADMAP_ES,
                   "current": roadmap_index(case, progress),
                   "future": FUTURE_EN if case.language.split("-")[0] == "en" else FUTURE_ES},
        "briefing_version": b.version if b else 0,
        "packet_ready": s.scalars(select(Packet).where(Packet.case_id == case.id, Packet.status == "current")).first()
        is not None,
        "reminders": reminders(s, case), "settings": cs.applicant_settings(case),
        "consent_given": cs.consent_given(s, case),
        "disclosure": _disclosure(case, clinic.name),
    }


# Dated things the applicant has to show up for; any other deadline kind is informational.
APPOINTMENTS = {"biometrics_appointment": "Biometrics appointment (fingerprints)", "interview": "USCIS interview",
                "oath_ceremony": "Oath ceremony"}


def _when(days: int, d: date) -> str:
    day = f"{d:%A}, {d:%B} {d.day}"
    if days < 0:
        return f"{-days} day{'s' if days < -1 else ''} ago ({day})"
    return "today" if days == 0 else f"tomorrow ({day})" if days == 1 else f"in {days} days ({day})"


def reminders(s: Session, case: Case) -> list[dict[str, Any]]:
    """Everything the applicant owes or should know about, most pressing first. `when` is computed here so
    the model can say it as-is (models never do date math).

    ponytail: hand-weighted score: action owed now > appointment by days left > missing document > info.
    pressing (score >= 80) is what the chat's opening mentions. Retune the weights here if the order feels off.
    """
    from .documents import document_label
    td = cs.today()
    out: list[dict[str, Any]] = []

    def add(kind, title, score, note="", on=None, action=None, when=None):
        days = (date.fromisoformat(on) - td).days if on else None
        out.append({"kind": kind, "title": title, "note": note, "date": on, "days_left": days,
                    "when": when or (_when(days, date.fromisoformat(on)) if on else None),
                    "pressing": score >= 80, "action": action, "score": score})

    clinic = s.get(Clinic, case.clinic_id)
    if s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.status == "case_blocked")).first():
        add("clinic", "Talk with your clinic", 95, "A person at your clinic needs to talk with you first.",
            action={"call": (clinic.settings or {}).get("phone")}, when="now")
    if case.state == "ready":
        add("sign", "Review and sign your application", 90, "Your clinic finished its review. Check each answer, "
            "then sign.", action={"page": "/review"}, when="now")
    for d in s.scalars(select(Deadline).where(Deadline.case_id == case.id, Deadline.status == "active",
                                              Deadline.date.is_not(None))):
        if d.kind not in APPOINTMENTS:
            continue
        days = (date.fromisoformat(d.date) - td).days
        if days < -1:
            continue  # past appointments drop off
        add("appointment", APPOINTMENTS[d.kind], 92 if days <= 3 else 82 if days <= 7 else 60 if days <= 30 else 35,
            d.note or "", on=d.date)
    # ponytail: only the latest upload of each type counts, so a good upload retires an earlier failed one (two
    # different "other" letters share a type: a failed one is hidden by any later one)
    latest = {d.document_type: d for d in s.scalars(select(Document).where(Document.case_id == case.id)
                                                     .order_by(Document.ts))}
    for doc in latest.values():
        if doc.status == "failed" or (doc.status == "extracted" and doc.quality == "low"):
            title = ("Upload your N-400 again" if doc.document_type == "n400"
                     else f"Retake the photo of your {document_label(doc.document_type, 'en')}")
            add("retake", title, 70, "We couldn't read it clearly.", action={"upload": doc.document_type},
                when="when you can")
    for g in cs.open_gaps(s, case.id):
        add("upload", f"Upload: {g.label_es or g.reason}", 60, "You need it before you file.",
            action={"upload": g.document_type}, when="before you file")
    der = cs.latest_derived(s, case.id)
    if der and der.data.get("earliest_filing") and case.state not in ("signed", "referred_out", "closed"):
        open_ = der.data.get("window_open")
        # the window is timing only: "you can file" waits for a signed form (this is what Ellis reads out too)
        title = ("Your filing window opens" if not open_ else "You can file your N-400" if case.state == "signed"
                 else "Your filing window is open")
        note = "By the rules engine; your clinic confirms it." + ("" if case.state == "signed" or not open_
                                                                 else " Finish and sign your form first.")
        add("filing", title, 30, note, on=None if open_ else der.data["earliest_filing"], when="now" if open_ else None)
    out.sort(key=lambda r: (-r["score"], r["days_left"] if r["days_left"] is not None else 9999))
    return out


FOCI = ("n400", "interview_prep", "reminders", "my_data", "settings", "clinic_question", "general")


def _my_answers(s: Session, case: Case) -> list[dict[str, Any]]:
    # masked fields reach the model only as their token, never the last four digits the screen shows
    return [{"section": g["label"], "label": i["label"], "status": i["chip"]["label"],
             "value": catalog.mask_token(i["field"]) if catalog.is_masked(i["field"]) else i["value"]}
            for g in facts_panel(s, case) for i in g["items"]]


def suggested_next(s: Session, case: Case, progress: list[dict[str, Any]]) -> dict[str, Any]:
    """The one step Ellis recommends first, in a focus shape; the applicant decides what to actually do.
    Same order as their screen: sign once the clinic is done, else the first unfinished N-400 part (the form's
    order), then missing documents, then interview practice."""
    if s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.status == "case_blocked")).first():
        return {"task": "clinic_question", "next_step": "Your clinic will contact you"}
    if case.state == "ready":
        return {"task": "general", "next_step": "Review and sign your answers", "link": "/review"}
    if case.state not in ("signed", "referred_out", "closed"):
        sec = next((p for p in progress if p["state"] not in ("done", "blocked")), None)
        if sec:
            return {"task": "n400", "section": sec["section"], "link": "/form",
                    "next_step": f"Answer the questions about {sec['label'].lower()}"}
        gap = next(iter(cs.open_gaps(s, case.id)), None)
        if gap:
            return {"task": "n400", "next_step": f"Upload: {gap.label_es or gap.reason}", "upload": gap.document_type}
    return {"task": "interview_prep", "next_step": "Practice for your interview", "link": "/interview"}


def agent_context(s: Session, case: Case, focus: dict[str, Any]) -> dict[str, Any]:
    """The conversation model's view of the case, rebuilt on every model call: the case at a glance, plus
    detail for whatever the applicant is doing right now (`focus`). Anything not in here or in a tool
    result, the model doesn't know."""
    from ..config import yaml_config
    lang = cs.case_lang(case)
    progress = section_progress(s, case)
    rem = reminders(s, case)
    task = focus.get("task", "general")
    ctx: dict[str, Any] = {
        "today": cs.today().isoformat(),
        "reply_language": languages.name(case.language),  # e.g. "French (Canada)": the language and accent
        "applicant": {"first_name": case.first_name, "case_state": case.state,
                      "consent_given": cs.consent_given(s, case)},
        "settings": cs.applicant_settings(case),
        "n400": {"complete": bool(progress) and all(p["state"] == "done" for p in progress),
                 "parts": [{"part": f"{i} of {len(progress)}", "key": p["section"], "label": p["label"],
                            "state": p["state"], "confirmed": f"{p['done']} of {p['total']}"}
                           for i, p in enumerate(progress, 1)]},
        "suggested_next_step": suggested_next(s, case, progress),
        "reminders": [r for r in rem if r["pressing"]][:3] or rem[:1],
    }
    if task == "n400":
        b = cs.liaison_briefing(s, case)
        view = cs.cur_view(s, case.id)
        label_of = catalog.label_en if lang == "en" else catalog.label_es
        sec_label = {p["section"]: p["label"] for p in progress}
        fallback = b.get("fallback", [])  # form order: the order of the parts on the applicant's screen
        sec = focus.get("section")
        seen: set = set()

        def items(src, cap):
            out = []
            for it in src:
                key = (it.get("kind"), it.get("field") or it.get("document_type") or it.get("section"))
                if key in seen or it.get("field") == "consent":
                    continue
                seen.add(key)
                f = it.get("field")
                out.append({**it, "part": sec_label.get(it.get("section"), it.get("section")),
                            **({"label": label_of(f), "question": catalog.question_for(f, view, lang)} if f else {})})
                if len(out) >= cap:
                    break
            return out
        need = items([it for it in fallback if it.get("section") == sec] + fallback, 12)
        ctx.update(still_needed=need, case_team_asks=items(b.get("queue", []), 4),
                   open_flag_categories=b.get("open_flag_categories"), rules=b.get("derived"),
                   # what's already saved (validated, masked), so nothing said once is asked again
                   answers={k: v for k, v in b["facts"].items() if k not in ("consent", "eligibility_basis")})
    elif task == "interview_prep":
        ctx.update(practice=yaml_config("practice.yaml"), my_answers=_my_answers(s, case))
    elif task == "reminders":
        ctx["reminders"] = rem
    elif task == "my_data":
        ctx.update(my_answers=_my_answers(s, case),
                   documents=[{"type": d.document_type, "status": d.status, "quality": d.quality}
                              for d in s.scalars(select(Document).where(Document.case_id == case.id))])
    elif task == "settings":
        ctx["setting_options"] = {k: list(v) for k, v in cs.APPLICANT_SETTINGS.items()}
    return ctx


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
        docs.append({"id": d.id, "document_type": d.document_type,
                     "document_label": LABELS_EN.get(d.document_type, catalog.title_key(d.document_type)),
                     "filename": d.filename, "status": d.status,
                     "quality": d.quality, "checks": d.checks, "exhibit": d.exhibit, "ts": d.ts.isoformat(),
                     "uploaded_by": d.uploaded_by, "extraction": x.data if x else None,
                     "extractor": x.extractor if x else None})
    event_rows = list(s.scalars(select(Event).where(Event.case_id == case.id).order_by(Event.id.desc()).limit(400)))
    events = [{"id": e.id, "kind": e.kind, "payload": e.payload, "actor_type": e.actor_type, "actor": e.actor,
               "ts": e.ts.isoformat(), "sentence": activity.describe(s, e, "en")}
              for e in event_rows]
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
        "labels": catalog.labels("en"),
        "document_types": [{"key": k, "label": v} for k, v in LABELS_EN.items()],
    }


def _disclosure(case: Case, clinic_name: str) -> str:
    from ..voice.liaison import script
    lang = "en" if (case.language or "en").split("-")[0] == "en" else "es"
    return script("disclosure", lang=lang, clinic_name=clinic_name).text


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
