"""One plain sentence per case event. Fixed templates, never a model.

Actors are Client liaison, Case manager, Paralegal, Docket clerk, QA reviewer, a staff name, or Client.
A system event with no person is Ellis.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db import Event, StaffUser
from .catalog import display_label

_AGENTS = {
    "case_manager": "Case manager",
    "doc_paralegal": "Paralegal",
    "docketing_clerk": "Docket clerk",
    "qa_reviewer": "QA reviewer",
    "liaison": "Client liaison",
}


def actor_name(s: Session, event: Event) -> str:
    kind = event.actor_type or "system"
    payload = event.payload or {}
    if kind == "applicant":
        return "Client"
    if kind == "liaison":
        return "Client liaison"
    if kind == "staff":
        user = s.get(StaffUser, event.actor) if event.actor else None
        return user.name if user and user.name else "Staff"
    if kind == "agent":
        return _AGENTS.get(payload.get("agent") or event.actor or "", "Case manager")
    if event.actor == "extraction_worker":
        return "Paralegal"
    return "Ellis"


def _field(payload: dict, lang: str) -> str:
    key = payload.get("field") or payload.get("section") or payload.get("document_type")
    if key:
        return display_label(str(key), lang)
    return ""


def describe(s: Session, event: Event, lang: str = "en") -> str:
    who = actor_name(s, event)
    payload = event.payload or {}
    field = _field(payload, lang)
    to = payload.get("to")
    sentences = {
        "session.started": f"{who} opened a conversation.",
        "session.ended": f"{who} ended the conversation.",
        "session.third_party": f"{who} noted someone else is with the client.",
        "stop.spoken": f"{who} paused for a sensitive topic.",
        "utterance.redacted": f"{who} hid a sensitive number from the transcript.",
        "readback.started": f"{who} read back {field}." if field else f"{who} started a read-back.",
        "readback.closed": f"{who} finished the read-back of {field}." if field else f"{who} finished a read-back.",
        "consent.given": "Client agreed to continue.",
        "consent.declined": "Client chose not to continue.",
        "fact.recorded": f"{who} saved {field}." if field else f"{who} saved an answer.",
        "fact.confirmed": f"{who} confirmed {field}." if field else f"{who} confirmed an answer.",
        "flag.raised": f"{who} flagged a topic for the clinic.",
        "flag.resolved": f"{who} resolved a flag.",
        "flag.self_report": "Client reported something for the clinic to review.",
        "section.deferred": f"{who} set a section aside for the clinic.",
        "section.undeferred": f"{who} reopened a deferred section.",
        "case.language_changed": "Client changed the language.",
        "case.settings_changed": f"{who} changed a case setting.",
        "case.state_changed": f"{who} moved the case to {to}." if to else f"{who} moved the case forward.",
        "case.created": f"{who} opened the case.",
        "case.reassigned": f"{who} reassigned the case.",
        "derived.computed": "Case manager updated the filing dates.",
        "rules.validation_error": "Case manager could not compute the filing dates.",
        "signoff.invalidated": f"{who} cleared the sign-off because an answer changed.",
        "signoff.recorded": "Client signed.",
        "proposal.rejected": f"{who} rejected a proposed change.",
        "briefing.published": "Case manager updated what Ellis will ask next.",
        "link.opened": "Client opened their link.",
        "link.issued": f"{who} sent a new link.",
        "account.attached": "Client attached an account.",
        "doc.uploaded": f"{who} uploaded a document.",
        "doc.extracted": "Paralegal read a document.",
        "doc.extraction_failed": "Paralegal could not read a document.",
        "vault.revealed": f"{who} revealed a hidden value.",
        "note.added": f"{who} added a note.",
        "staff.invited": f"{who} invited a staff member.",
        "staff.changed": f"{who} updated a staff account.",
        "staff.login": f"{who} signed in.",
        "clinic.created": f"{who} created the clinic.",
        "clinic.settings_changed": f"{who} updated clinic settings.",
        "gap.declined": "Client declined a document request.",
        "gap.opened": f"{who} opened a document gap.",
        "gap.closed": f"{who} closed a document gap.",
        "representation.chosen": "Client chose who files.",
        "agent.run_failed": f"{who} could not finish a run.",
        "agent.run_applied": f"{who} applied their work to the case.",
        "task.created": f"{who} added a task.",
        "memo.written": f"{who} wrote a memo.",
        "deadline.set": "Docket clerk set a date.",
        "review.evidence_attached": f"{who} attached evidence to a review item.",
        "review.reopened": "Client reopened a section.",
        "review.decision": f"{who} decided a review item.",
        "packet.built": "Docket clerk built the packet.",
    }
    if event.kind in sentences:
        return sentences[event.kind]
    label = field or display_label(event.kind.replace(".", " "), lang)
    return f"Case updated: {label}."
