"""Clinic reviewer decisions and the Mark-ready gate."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Case, Flag, ReviewItem, StaffUser, Task, now
from . import case_service as cs
from .flags import DECISIONS, STOP_NOW


def decide(s: Session, item: ReviewItem, decision: str, note: str, staff: StaffUser) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise cs.CaseError("bad_decision", f"unknown decision {decision}")
    if not (note or "").strip():
        raise cs.CaseError("note_required", "every decision requires a note", "note")
    case = s.get(Case, item.case_id)
    fl = s.get(Flag, item.flag_id) if item.flag_id else None
    if item.speed == STOP_NOW and decision in ("clear", "clear_with_referral"):
        raise cs.CaseError("stop_now_requires_professional",
                           "stop-now items close only as resolved by a professional (or not about the applicant)")
    if decision == "resolved_by_professional" and item.speed != STOP_NOW:
        raise cs.CaseError("stop_now_only", "resolved_by_professional is for stop-now items")
    if decision == "not_about_applicant" and not (fl and fl.applicant_self_report):
        raise cs.CaseError("no_self_report", "only after the applicant tapped 'Esto no era sobre mí'")
    item.decision = decision
    item.decision_note = note.strip()
    item.decided_by = staff.id
    item.decided_at = now()
    if DECISIONS[decision]:
        item.status = "closed"
        if fl is not None:
            fl.status = "resolved"
    elif decision == "block_case":
        item.status = "case_blocked"
    else:  # needs_more_info: stays open, the note becomes a question for the liaison
        item.status = "open"
        s.add(Task(clinic_id=case.clinic_id, case_id=case.id, agent="reviewer", kind="question",
                   title=f"Reviewer needs more info: {note.strip()}", field=f"followup.{item.id}",
                   question_es=note.strip(), proposed_by=f"staff:{staff.id}", ts=now()))
    blocking = s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.blocking.is_(True),
                                                  ReviewItem.status.in_(["open", "case_blocked"]))).all()
    cs.emit(s, case, "review.decision", {"item_id": item.id, "decision": decision, "category": item.category
                                         if item.speed != STOP_NOW else None, "speed": item.speed,
                                         "blocking_count": len(blocking)}, "staff", staff.id)
    if decision == "not_about_applicant" and item.speed == STOP_NOW and fl is not None:
        _undefer(s, case, fl)
    return {"item_id": item.id, "status": item.status, "blocking_count": len(blocking)}


def _undefer(s: Session, case: Case, fl: Flag) -> None:
    """A false-positive stop: deferred placeholders are removed so the section can be asked normally."""
    for f in cs.facts_for(s, case.id):
        if f.provenance.get("flag_id") == fl.id:
            f.status = "superseded"
            f.note = "stop cleared as not about the applicant"
    cs.emit(s, case, "section.undeferred", {"section": fl.section}, "staff", "reviewer")
    cs.after_fact_change(s, case)


def mark_ready(s: Session, case: Case, staff: StaffUser) -> dict[str, Any]:
    if case.state not in ("review", "evidence", "intake"):
        raise cs.CaseError("bad_state", f"case is {case.state}", status=409)
    gate = cs.gate_status(s, case)
    if not gate["passes"]:
        err = cs.CaseError("gate_failed", "the ready gate does not pass", status=409)
        err.details = gate["failing"]  # type: ignore[attr-defined]
        raise err
    cs.set_state(s, case, "ready", "reviewer marked ready", "staff", staff.id)
    return {"state": case.state}


def self_report(s: Session, case: Case, flag_id: str) -> None:
    fl = s.get(Flag, flag_id)
    if fl is None or fl.case_id != case.id:
        raise cs.CaseError("not_found", "flag not found", status=404)
    fl.applicant_self_report = True
    cs.emit(s, case, "flag.self_report", {"flag_id": fl.id}, "applicant", "applicant")
