"""Review screen (A8), reopen, sign-off and packet build."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Case, Packet, Signoff, now
from . import case_service as cs
from . import catalog, keywords
from .values import display_value

ATTESTATION_VERSION = {"es": "es-1", "en": "en-1"}
ATTESTATION_TEXT = {
    "es": ("Revisé todas mis respuestas y son verdaderas según mi conocimiento. "
          "Entiendo que Ellis no envía mi solicitud."),
    "en": ("I reviewed all my answers and they are true to my knowledge. "
          "I understand that Ellis does not submit my application."),
}
DEFERRED_TEXT = {"es": "Para completar con su profesional con licencia",
                 "en": "To complete with your licensed professional"}


case_lang = cs.case_lang  # re-exported so evals/flows.py and others keep one source of truth


def review_view(s: Session, case: Case) -> dict[str, Any]:
    lang = case_lang(case)
    cur = cs.current_facts(s, case.id)
    sections = []
    for sec in catalog.sections():
        items = []
        for key, f in cur.items():
            if catalog.section_of(key) != sec["key"] or key == "consent":
                continue
            v = f.value
            if catalog.is_masked(key):
                last4 = cs.vault_last4(s, f.id)
                shown = f"•••• {last4}" if last4 else "••••"
            elif v == catalog.DEFERRED:
                shown = DEFERRED_TEXT[lang]
            else:
                shown = cs.spoken_value(key, v, lang=lang) if not isinstance(v, str) or catalog.is_date_field(key) else str(v)
            label = catalog.label_en(key) if lang == "en" else catalog.label_es(key)
            items.append({"field": key, "label": label, "value": shown, "status": f.status,
                          "deferred": v == catalog.DEFERRED})
        if items:
            sec_label = sec.get("label_en") if lang == "en" else sec["label_es"]
            sections.append({"key": sec["key"], "label": sec_label or sec["label_es"],
                             "items": sorted(items, key=lambda i: _order(i["field"]))})
    return {"sections": sections, "attestation_text": ATTESTATION_TEXT[lang],
            "attestation_version": ATTESTATION_VERSION[lang], "state": case.state}


def _order(key: str) -> tuple:
    m = catalog.LIST_RE.match(key)
    return (m["list"], int(m["i"]), key) if m else (key, 0, key)


def reopen(s: Session, case: Case, section: str) -> None:
    if case.state not in ("ready", "review", "signed"):
        raise cs.CaseError("bad_state", "nothing to reopen yet", status=409)
    cs.emit(s, case, "review.reopened", {"section": section}, "applicant", "applicant")
    case.material_changed_at = now()
    if case.state in ("ready", "signed"):
        for so in s.scalars(select(Signoff).where(Signoff.case_id == case.id, Signoff.valid.is_(True))):
            so.valid = False
        cs.set_state(s, case, "review", f"applicant reopened {section}", "applicant", "applicant")


def sign(s: Session, case: Case, typed_name: str, attestation_version: str, user_agent: str | None,
         section_confirmations: dict | None = None, read_aloud: bool = False,
         assisted_by: str | None = None) -> dict[str, Any]:
    if case.state != "ready":
        raise cs.CaseError("not_ready", "the case is not ready for sign-off", status=409)
    lang = case_lang(case)
    if attestation_version != ATTESTATION_VERSION[lang]:
        raise cs.CaseError("attestation_version", "unknown attestation version")
    vals = cs.fact_values(s, case.id)
    legal = f"{vals.get('name.given', case.first_name)} {vals.get('name.family', case.last_name)}"
    if keywords.fold(typed_name) != keywords.fold(legal):
        msg = ("Type your name as it appears on your documents." if lang == "en"
              else "Escriba su nombre como aparece en sus documentos.")
        raise cs.CaseError("name_mismatch", msg, "typed_name")
    gate = cs.gate_status(s, case)
    if not gate["passes"]:
        raise cs.CaseError("gate", "the case no longer passes the gate", status=409)
    ids, h = cs.facts_hash(s, case.id)
    so = Signoff(clinic_id=case.clinic_id, case_id=case.id, typed_name=typed_name,
                 attestation_version=attestation_version, section_confirmations=section_confirmations or {},
                 fact_ids=ids, facts_hash=h, user_agent=(user_agent or "")[:300], read_aloud=read_aloud,
                 assisted_by=assisted_by, ts=now())
    s.add(so)
    s.flush()
    cs.emit(s, case, "signoff.recorded", {"signoff_id": so.id, "read_aloud": read_aloud, "assisted_by": assisted_by},
            "applicant", "applicant")
    for old in s.scalars(select(Packet).where(Packet.case_id == case.id, Packet.status == "current")):
        old.status = "stale"
    from ..packet.builder import build_packet
    packets = build_packet(s, case, so)
    case.signed_at = now()
    cs.set_state(s, case, "signed", "applicant signed", "applicant", "applicant")
    return {"signoff_id": so.id, "packet": [{"id": p.id, "kind": p.kind, "filename": p.filename} for p in packets]}


def professional_draft(s: Session, case: Case) -> Packet:
    from ..packet.builder import build_packet
    return build_packet(s, case, None, kinds=["professional_draft"])[0]


def summary_rows(s: Session, case: Case) -> list[dict[str, Any]]:
    cur = cs.current_facts(s, case.id)
    return [{"field": k, "label": catalog.label_en(k), "value": display_value(k, f.value)} for k, f in cur.items()]
