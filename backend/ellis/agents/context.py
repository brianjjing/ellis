"""Context builder: what a staff agent may see. Masked identifiers only; never utterance text; stop-now items
reduced to {flag_id, speed, section}; never raw document images."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Case, Deadline, Document, Event, Extraction, Gap, Memo, ReviewItem, Task
from ..services import case_service as cs
from ..services import catalog
from ..services.flags import STOP_NOW


def build_context(s: Session, case: Case, trigger_events: list[int] | None = None) -> dict[str, Any]:
    view = cs.cur_view(s, case.id)
    facts = {}
    for k, v in view.items():
        val = catalog.mask_token(k) if catalog.is_masked(k) else v["value"]
        if k.startswith("addresses[") and k.endswith(".street"):
            val = "[STREET]"
        facts[k] = {"value": val, "status": v["status"], "source": v["source"], "hedge": v["hedge"],
                    "third_party": v["third_party"], "conflict": v["conflict"]}
    flags = []
    for fl in cs.all_open_flags(s, case):
        if fl.speed == STOP_NOW:
            flags.append({"flag_id": fl.id, "speed": STOP_NOW, "section": fl.section})
        else:
            flags.append({"flag_id": fl.id, "speed": fl.speed, "category": fl.category, "field": fl.field,
                          "layer": fl.layer, "rule_id": fl.rule_id, "detail": {k: v for k, v in (fl.detail or {}).items()
                                                                              if k in ("days", "documents", "note")}})
    docs = []
    for d in s.scalars(select(Document).where(Document.case_id == case.id).order_by(Document.ts)):
        x = s.scalars(select(Extraction).where(Extraction.document_id == d.id).order_by(Extraction.ts.desc())).first()
        docs.append({"id": d.id, "document_type": d.document_type, "status": d.status, "quality": d.quality,
                     "checks": d.checks, "exhibit": d.exhibit, "uploaded_at": d.ts.isoformat(),
                     "extraction": (x.data if x else None), "quality_reasons": (x.quality_reasons if x else [])})
    der = cs.latest_derived(s, case.id)
    b = cs.latest_briefing(s, case.id)
    tasks = [{"id": t.id, "agent": t.agent, "kind": t.kind, "title": t.title, "field": t.field, "status": t.status,
              "round": t.round, "question_es": t.question_es, "ts": t.ts.isoformat()}
             for t in s.scalars(select(Task).where(Task.case_id == case.id).order_by(Task.ts.desc()).limit(40))]
    reviews = []
    for r in s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id).order_by(ReviewItem.ts)):
        if r.speed == STOP_NOW:
            reviews.append({"id": r.id, "speed": STOP_NOW, "status": r.status, "blocking": r.blocking})
        else:
            reviews.append({"id": r.id, "category": r.category, "field": r.field, "status": r.status,
                            "blocking": r.blocking, "decision": r.decision, "decision_note": r.decision_note,
                            "evidence": r.evidence, "agent_notes": r.agent_notes})
    gaps = [{"id": g.id, "key": g.key, "document_type": g.document_type, "status": g.status, "label_es": g.label_es}
            for g in s.scalars(select(Gap).where(Gap.case_id == case.id))]
    memos = [{"kind": m.kind, "ts": m.ts.isoformat()} for m in
             s.scalars(select(Memo).where(Memo.case_id == case.id).order_by(Memo.ts.desc()).limit(5))]
    deadlines = [{"kind": d.kind, "date": d.date, "rule": d.date_from_rule, "note": d.note} for d in
                 s.scalars(select(Deadline).where(Deadline.case_id == case.id, Deadline.status == "active"))]
    events = []
    if trigger_events:
        for e in s.scalars(select(Event).where(Event.id.in_(trigger_events))):
            p = dict(e.payload)
            if e.kind == "flag.raised" and p.get("speed") == STOP_NOW:
                p = {"flag_id": p.get("flag_id"), "speed": STOP_NOW, "section": p.get("section")}
            events.append({"id": e.id, "kind": e.kind, "payload": {k: v for k, v in p.items()
                                                                    if k not in ("old", "new")} | (
                {"old": p.get("old"), "new": p.get("new")} if e.kind == "fact.corrected"
                and not catalog.is_masked(p.get("field", "")) else {})})
    missing = catalog.missing_required(view, der.data if der else None, cs.today(), confirmed=False)
    ctx = {
        "case": {"id": case.id, "state": case.state, "first_name": case.first_name,
                 "patient_mode": bool((case.settings or {}).get("patient_mode")),
                 "material_changed_at": case.material_changed_at.isoformat() if case.material_changed_at else None},
        "today": cs.today().isoformat(),
        "facts": facts, "open_flags": flags, "documents": docs, "derived": der.data if der else None,
        "derived_id": der.id if der else None, "last_briefing": b.body if b else None, "tasks": tasks,
        "review_items": reviews, "gaps": gaps, "memos": memos, "deadlines": deadlines, "trigger_events": events,
        "missing_required": missing[:40], "gate": cs.gate_status(s, case),
        "deferred_sections": sorted(cs.deferred_sections(s, case)),
        "latest_event_id": s.scalars(select(Event.id).where(Event.case_id == case.id).order_by(Event.id.desc())
                                     .limit(1)).first(),
    }
    return ctx


def context_hash(ctx: dict) -> str:
    return hashlib.sha256(json.dumps(ctx, sort_keys=True, default=str).encode()).hexdigest()[:16]
