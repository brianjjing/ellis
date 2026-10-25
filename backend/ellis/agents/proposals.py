"""Proposal envelope schema, authority limits, and how the Case API applies a proposal.

Agents never write: they return proposals. Each item is checked against the agent's authority; disallowed
items are dropped and logged as proposal.rejected. Every proposal carries a run_id; duplicates apply once.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import AgentRun, Case, Deadline, Document, Event, Gap, Memo, ReviewItem, Task, TravelCandidate, now
from ..services import case_service as cs
from ..services import catalog
from ..services.flags import CATEGORIES, STOP_NOW

_log = logging.getLogger(__name__)
_CITATION_DOMAINS = frozenset(["uscis.gov", "ecfr.gov", "federalregister.gov"])


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["briefing", "task", "review_item", "gap", "gap_close", "memo", "deadline", "evidence",
                  "doc_checks", "review_note", "travel_candidate", "non_issue"]
    payload: dict[str, Any]


class Envelope(BaseModel):
    model_config = ConfigDict(extra="ignore")
    agent: str
    run_id: str
    case_id: str
    based_on_event_id: Optional[int] = None
    items: list[Item] = Field(default_factory=list)


class TaskP(BaseModel):
    title: str
    title_es: Optional[str] = None
    kind: Literal["finding", "question", "challenge"]
    field: Optional[str] = None
    question_es: Optional[str] = None
    links: list[str] = Field(default_factory=list)
    citation: Optional[dict] = None  # validated separately so a bad citation never rejects the task


class ReviewItemP(BaseModel):
    category: str
    field: Optional[str] = None
    note: str
    citation: Optional[dict] = None  # validated separately so a bad citation never rejects the item


class CitationP(BaseModel):
    rule: str
    url: str
    retrieved_at: str
    quote: str


class TravelCandidateP(BaseModel):
    trip_index: int
    departure_date: str
    return_date: Optional[str] = None
    departure_source: Literal["i94", "passport_stamp", "missing"]
    return_source: Literal["i94", "passport_stamp", "missing"]
    source_document_ids: list[str] = Field(default_factory=list)
    note: Optional[str] = None


class NonIssueP(BaseModel):
    field: Optional[str] = None
    note: str


class GapP(BaseModel):
    document_type: str
    reason: str
    label_es: Optional[str] = None
    key: str


class GapCloseP(BaseModel):
    key: str
    document_id: str


class MemoP(BaseModel):
    kind: Literal["status", "qa"]
    body_md: str


class DeadlineP(BaseModel):
    kind: str
    date_from_rule: Optional[str] = None
    note: Optional[str] = None


class EvidenceP(BaseModel):
    category: str
    field: Optional[str] = None
    document_id: str


class DocChecksP(BaseModel):
    document_id: str
    checks: dict[str, Any]
    exhibit: Optional[str] = None


class ReviewNoteP(BaseModel):
    category: str
    field: Optional[str] = None
    note: str


class BriefingP(BaseModel):
    queue: list[dict[str, Any]] = Field(default_factory=list)
    tone_hint: Optional[str] = None
    applicant_visible_flags: list[str] = Field(default_factory=list)
    reviewer_notes_for_applicant: list[str] = Field(default_factory=list)
    session_close: Optional[dict[str, Any]] = None


# Paralegal gap keys. The trailing colon is part of the flag and document formats.
_FLAG_GAP_KEY = re.compile(r"^flag:([a-z0-9_]+):$")
_REVIEW_GAP_KEY = re.compile(r"^review:([a-z0-9_]+):([A-Za-z0-9_.\[\]]+)$")
_DOC_GAP_KEY = re.compile(r"^doc:([a-z0-9_]+):$")
_STOP_GAP_TOKENS = ("criminal", "arrest", "removal")


def gap_key_blocked(key: str) -> bool:
    """A gap key names a stop-now topic and must not be stored.

    Recognized paralegal keys are ``flag:<flag_type>:``, ``review:<category>:<field>``,
    and ``doc:<document_type>:``. Only the segment that names the topic is checked.
    Other keys keep the older whole-string check so existing skeleton keys still store.
    """
    flag = _FLAG_GAP_KEY.fullmatch(key)
    if flag:
        return _gap_token_blocked(flag.group(1))
    review = _REVIEW_GAP_KEY.fullmatch(key)
    if review:
        return _gap_token_blocked(review.group(1)) or _gap_token_blocked(review.group(2))
    doc = _DOC_GAP_KEY.fullmatch(key)
    if doc:
        return _gap_token_blocked(doc.group(1))
    return any(key.startswith(tok) or tok in key for tok in _STOP_GAP_TOKENS)


def _gap_token_blocked(token: str) -> bool:
    return any(tok in token for tok in _STOP_GAP_TOKENS)


PAYLOADS = {"task": TaskP, "review_item": ReviewItemP, "gap": GapP, "gap_close": GapCloseP, "memo": MemoP,
            "deadline": DeadlineP, "evidence": EvidenceP, "doc_checks": DocChecksP, "review_note": ReviewNoteP,
            "briefing": BriefingP, "travel_candidate": TravelCandidateP, "non_issue": NonIssueP}

# What each agent may propose (spec: Staff agents → May propose).
AUTHORITY: dict[str, dict[str, Any]] = {
    "case_manager": {"types": {"briefing", "task", "memo", "review_item"}, "memo_kinds": {"status"},
                     "task_kinds": {"finding", "question"}, "review_categories": {"other_path"}},
    "doc_paralegal": {"types": {"gap", "gap_close", "task", "review_item", "evidence", "doc_checks",
                                "travel_candidate", "non_issue"},
                      "task_kinds": {"finding"}, "review_categories": {"document_conflict", "name_mismatch",
                                                                       "document_owner"}},
    "docketing_clerk": {"types": {"deadline", "task"}, "task_kinds": {"finding"}},
    "qa_reviewer": {"types": {"task", "review_item", "memo", "review_note"}, "memo_kinds": {"qa"},
                    "task_kinds": {"challenge", "finding"},
                    "review_categories": set(CATEGORIES) - {"arrest", "removal", "citizenship_claim", "fraud",
                                                             "danger"}},
}


def validate_envelope(raw: Any, agent: str, case_id: str) -> Envelope:
    """Raises ValidationError / ValueError when the output does not match the schema."""
    env = Envelope.model_validate(raw)
    if env.agent != agent or env.case_id != case_id:
        raise ValueError("envelope agent/case mismatch")
    for it in env.items:
        PAYLOADS[it.type].model_validate(it.payload)
    return env


def _validate_citation(s: Session, case: Case, agent: str, run_id: str, raw: dict, who: str,
                       rejected: list) -> dict | None:
    """Return a clean citation dict, or None (logs and adds to rejected, but does NOT reject the parent item)."""
    try:
        netloc = urlparse(raw.get("url", "")).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if netloc not in _CITATION_DOMAINS:
            raise ValueError(f"citation URL domain not allowed: {netloc}")
        quote = raw.get("quote", "")
        if len(quote.split()) > 25:
            raise ValueError(f"citation quote exceeds 25 words ({len(quote.split())} words)")
        return {"rule": raw.get("rule", ""), "url": raw["url"], "retrieved_at": raw.get("retrieved_at", ""),
                "quote": quote}
    except (ValueError, KeyError) as exc:
        reason = str(exc)
        _log.warning("citation dropped for %s@%s: %s", agent, run_id, reason)
        cs.emit(s, case, "proposal.rejected", {"agent": agent, "run_id": run_id, "type": "citation",
                                               "reason": reason}, "agent", who)
        rejected.append({"type": "citation", "reason": reason})
        return None


def _reject(s: Session, case: Case, agent: str, run_id: str, item: Item, reason: str, rejected: list) -> None:
    rejected.append({"type": item.type, "reason": reason})
    cs.emit(s, case, "proposal.rejected", {"agent": agent, "run_id": run_id, "type": item.type, "reason": reason},
            "agent", f"{agent}@{run_id}")


def _stop_fields(s: Session, case: Case) -> set[str]:
    return {k for k, v in cs.cur_view(s, case.id).items() if v["value"] == catalog.DEFERRED}


def apply_proposal(s: Session, env: Envelope, backend: str = "skeleton", ms: int | None = None,
                   trigger_events: list[int] | None = None, model: str | None = None) -> dict[str, Any]:
    case = s.get(Case, env.case_id)
    existing = s.get(AgentRun, env.run_id)
    if existing is not None and existing.status == "applied":
        return {"duplicate": True, "accepted": existing.accepted_items, "rejected": existing.rejected_items}
    who = f"{env.agent}@{env.run_id}"
    auth = AUTHORITY.get(env.agent, {"types": set()})
    accepted, rejected = [], []
    latest_material = s.scalars(select(Event.id).where(Event.case_id == case.id, Event.kind.in_(
        ["fact.recorded", "fact.corrected", "fact.confirmed", "flag.raised", "doc.extracted", "review.decision"]))
        .order_by(Event.id.desc()).limit(1)).first()
    for item in env.items:
        if item.type not in auth["types"]:
            _reject(s, case, env.agent, env.run_id, item, "outside authority", rejected)
            continue
        p = PAYLOADS[item.type].model_validate(item.payload)
        try:
            if item.type == "briefing":
                if env.based_on_event_id is not None and latest_material and env.based_on_event_id < latest_material:
                    _reject(s, case, env.agent, env.run_id, item, "stale: a newer run will follow", rejected)
                    continue
                b = cs.latest_briefing(s, case.id)
                body = p.model_dump()
                if b is not None and _same_briefing(b.body, body):
                    continue
                nb = cs.publish_briefing(s, case, body, proposed_by=who, based_on_event_id=env.based_on_event_id)
                accepted.append({"type": "briefing", "version": nb.version})
            elif item.type == "task":
                if p.kind not in auth.get("task_kinds", set()):
                    _reject(s, case, env.agent, env.run_id, item, f"task kind {p.kind} not allowed", rejected)
                    continue
                if p.field and (p.field in _stop_fields(s, case) or p.field.startswith("background.criminal")):
                    _reject(s, case, env.agent, env.run_id, item, "names a stop-now section", rejected)
                    continue
                if _dup_task(s, case, env.agent, p):
                    continue
                rnd = 1
                if p.kind == "challenge":
                    rnd = _challenge_round(s, case) + 1
                    if rnd > 2:
                        _reject(s, case, env.agent, env.run_id, item, "max 2 challenge rounds", rejected)
                        continue
                citation = (_validate_citation(s, case, env.agent, env.run_id, p.citation, who, rejected)
                            if p.citation else None)
                t = Task(clinic_id=case.clinic_id, case_id=case.id, agent=env.agent, kind=p.kind, title=p.title,
                         title_es=p.title_es, field=p.field, question_es=p.question_es, links=p.links,
                         citation=citation, round=rnd, proposed_by=who, ts=now())
                s.add(t)
                s.flush()
                cs.emit(s, case, "task.created", {"task_id": t.id, "agent": env.agent, "kind": p.kind}, "agent", who)
                accepted.append({"type": "task", "id": t.id})
            elif item.type == "review_item":
                if p.category not in auth.get("review_categories", set()):
                    _reject(s, case, env.agent, env.run_id, item, f"category {p.category} not allowed", rejected)
                    continue
                citation = (_validate_citation(s, case, env.agent, env.run_id, p.citation, who, rejected)
                            if p.citation else None)
                fl = cs.raise_flag(s, case, p.category, layer=2 if env.agent != "qa_reviewer" else 2, field=p.field,
                                   detail={"note": p.note, "by": who}, actor=who, actor_type="agent")
                if fl is None:
                    _add_note(s, case, p.category, p.field, p.note, who)
                else:
                    for ri in s.scalars(select(ReviewItem).where(ReviewItem.flag_id == fl.id)):
                        ri.agent_notes = [*ri.agent_notes, {"by": who, "note": p.note}]
                        ri.proposed_by = who
                        if citation and ri.citation is None:
                            ri.citation = citation
                accepted.append({"type": "review_item", "category": p.category})
            elif item.type == "travel_candidate":
                existing_tc = s.scalars(select(TravelCandidate).where(
                    TravelCandidate.case_id == case.id, TravelCandidate.trip_index == p.trip_index,
                    TravelCandidate.status == "pending")).first()
                if existing_tc is not None:
                    continue  # already have a pending candidate for this trip index
                tc = TravelCandidate(clinic_id=case.clinic_id, case_id=case.id, trip_index=p.trip_index,
                                     departure_date=p.departure_date, return_date=p.return_date,
                                     departure_source=p.departure_source, return_source=p.return_source,
                                     source_document_ids=p.source_document_ids, note=p.note,
                                     proposed_by=who, ts=now())
                s.add(tc)
                s.flush()
                cs.emit(s, case, "travel_candidate.created",
                        {"travel_candidate_id": tc.id, "trip_index": p.trip_index, "agent": env.agent},
                        "agent", who)
                accepted.append({"type": "travel_candidate", "id": tc.id, "trip_index": p.trip_index})
            elif item.type == "non_issue":
                cs.emit(s, case, "non_issue.noted",
                        {"agent": env.agent, "field": p.field, "note": p.note}, "agent", who)
                accepted.append({"type": "non_issue", "field": p.field})
            elif item.type == "review_note":
                if _add_note(s, case, p.category, p.field, p.note, who):
                    accepted.append({"type": "review_note"})
            elif item.type == "gap":
                if gap_key_blocked(p.key):
                    _reject(s, case, env.agent, env.run_id, item, "no documents for stop-now sections", rejected)
                    continue
                if s.scalars(select(Gap).where(Gap.case_id == case.id, Gap.key == p.key)).first():
                    continue
                g = Gap(clinic_id=case.clinic_id, case_id=case.id, document_type=p.document_type, reason=p.reason,
                        label_es=p.label_es, key=p.key, proposed_by=who, ts=now())
                s.add(g)
                s.flush()
                cs.emit(s, case, "gap.opened", {"gap_id": g.id, "document_type": p.document_type}, "agent", who)
                accepted.append({"type": "gap", "id": g.id})
            elif item.type == "gap_close":
                # Same key the paralegal stored: flag:<type>:, review:<category>:<field>, or doc:<type>:.
                if gap_key_blocked(p.key):
                    _reject(s, case, env.agent, env.run_id, item, "no documents for stop-now sections", rejected)
                    continue
                g = s.scalars(select(Gap).where(Gap.case_id == case.id, Gap.key == p.key, Gap.status == "open")).first()
                d = s.get(Document, p.document_id)
                if g is None or d is None or d.case_id != case.id:
                    continue
                g.status = "closed"
                g.closed_by_document = d.id
                cs.emit(s, case, "gap.closed", {"gap_id": g.id, "document_id": d.id}, "agent", who)
                accepted.append({"type": "gap_close", "id": g.id})
            elif item.type == "memo":
                if p.kind not in auth.get("memo_kinds", set()):
                    _reject(s, case, env.agent, env.run_id, item, f"memo kind {p.kind} not allowed", rejected)
                    continue
                last = s.scalars(select(Memo).where(Memo.case_id == case.id, Memo.kind == p.kind)
                                 .order_by(Memo.ts.desc())).first()
                if last is not None and last.body_md == p.body_md and p.kind == "status":
                    continue
                m = Memo(clinic_id=case.clinic_id, case_id=case.id, kind=p.kind, body_md=p.body_md, proposed_by=who,
                         ts=now())
                s.add(m)
                s.flush()
                cs.emit(s, case, "memo.written", {"memo_id": m.id, "kind": p.kind}, "agent", who)
                accepted.append({"type": "memo", "id": m.id})
            elif item.type == "deadline":
                der = cs.latest_derived(s, case.id)
                rule_dates = {"R-ELIG-EARLY": "earliest_filing", "R-ANNIV": "anniversary"}
                dt = None
                if p.date_from_rule:
                    key = rule_dates.get(p.date_from_rule)
                    if key is None or der is None or not der.data.get(key):
                        _reject(s, case, env.agent, env.run_id, item, "date must come from the rules engine", rejected)
                        continue
                    dt = der.data[key]
                cur = s.scalars(select(Deadline).where(Deadline.case_id == case.id, Deadline.kind == p.kind,
                                                       Deadline.status == "active")).first()
                if cur is not None and cur.date == dt and cur.note == p.note:
                    continue
                if cur is not None:
                    cur.status = "superseded"
                s.add(Deadline(clinic_id=case.clinic_id, case_id=case.id, kind=p.kind, date=dt,
                               date_from_rule=p.date_from_rule, note=p.note, proposed_by=who, ts=now()))
                cs.emit(s, case, "deadline.set", {"kind": p.kind, "date": dt, "rule": p.date_from_rule}, "agent", who)
                accepted.append({"type": "deadline", "kind": p.kind})
            elif item.type == "evidence":
                ri = s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.category == p.category,
                                                        ReviewItem.status == "open")).first()
                d = s.get(Document, p.document_id)
                if ri is None or d is None or ri.speed == STOP_NOW or p.document_id in (ri.evidence or []):
                    continue
                ri.evidence = [*(ri.evidence or []), p.document_id]
                cs.emit(s, case, "review.evidence_attached", {"item_id": ri.id, "document_id": d.id}, "agent", who)
                accepted.append({"type": "evidence"})
            elif item.type == "doc_checks":
                d = s.get(Document, p.document_id)
                if d is None or d.case_id != case.id:
                    continue
                new = {**(d.checks or {}), **p.checks}
                if new != d.checks or (p.exhibit and p.exhibit != d.exhibit):
                    d.checks = new
                    if p.exhibit:
                        d.exhibit = p.exhibit
                    accepted.append({"type": "doc_checks", "document_id": d.id})
        except cs.CaseError as e:
            _reject(s, case, env.agent, env.run_id, item, e.message, rejected)
    run = existing or AgentRun(id=env.run_id, clinic_id=case.clinic_id, case_id=case.id, agent=env.agent,
                               backend=backend, trigger_events=trigger_events or [], model=model,
                               prompt_version="v1", ts=now())
    run.output = env.model_dump()
    run.accepted_items = accepted
    run.rejected_items = rejected
    run.status = "applied"
    run.ms = ms
    if existing is None:
        s.add(run)
    if accepted or rejected:
        cs.emit(s, case, "agent.run_applied", {"agent": env.agent, "run_id": env.run_id,
                                               "accepted": len(accepted), "rejected": len(rejected)}, "agent", who)
    cs.after_fact_change(s, case)
    return {"duplicate": False, "accepted": accepted, "rejected": rejected}


def _same_briefing(old: dict, new: dict) -> bool:
    keys = ("queue", "tone_hint", "applicant_visible_flags", "reviewer_notes_for_applicant", "session_close")
    return all((old.get(k) or None) == (new.get(k) or None) for k in keys)


def _dup_task(s: Session, case: Case, agent: str, p: TaskP) -> bool:
    last = s.scalars(select(Task).where(Task.case_id == case.id, Task.agent == agent).order_by(Task.ts.desc())
                     .limit(10)).all()
    if p.kind == "challenge" or p.kind == "question":
        return any(t.title == p.title and t.status == "open" for t in last) or any(
            t.title == p.title for t in s.scalars(select(Task).where(Task.case_id == case.id, Task.title == p.title)))
    return bool(last) and last[0].title == p.title


def _challenge_round(s: Session, case: Case) -> int:
    q = select(Task).where(Task.case_id == case.id, Task.agent == "qa_reviewer", Task.kind == "challenge")
    if case.material_changed_at is not None:
        q = q.where(Task.ts >= case.material_changed_at)
    rounds = {t.round for t in s.scalars(q)}
    return max(rounds) if rounds else 0


def _add_note(s: Session, case: Case, category: str, field: str | None, note: str, who: str) -> bool:
    q = select(ReviewItem).where(ReviewItem.case_id == case.id, ReviewItem.category == category,
                                 ReviewItem.status == "open")
    if field:
        q = q.where(ReviewItem.field == field)
    ri = s.scalars(q).first()
    if ri is None or ri.speed == STOP_NOW:
        return False
    if any(n.get("note") == note for n in ri.agent_notes or []):
        return False
    ri.agent_notes = [*(ri.agent_notes or []), {"by": who, "note": note}]
    return True


__all__ = ["Envelope", "Item", "validate_envelope", "apply_proposal", "ValidationError", "AUTHORITY",
           "gap_key_blocked", "TravelCandidateP", "CitationP", "NonIssueP"]
