"""Load the synthetic demo data with one command:

    uv run python -m seed.load            # drop + recreate all tables, then seed

Clinic "Clínica Comunitaria del Valle (demo)", three staff users and the four flow applicants.
Applicant links use fixed demo tokens (printed at the end); staff password for all demo users: ellis-demo
"""

from __future__ import annotations

import os

from ellis.db import Case, Clinic, Document, StaffUser, create_all, drop_all, now, session_scope
from ellis.services import auth
from ellis.services import case_service as cs
from ellis.services import documents as docs
from ellis.services.demo import simulate_answers

from . import specimens
from .scripts import JORGE

DEMO_PASSWORD = "ellis-demo"
LINKS = {"c_maria": "demo-maria", "c_jorge": "demo-jorge", "c_ana": "demo-ana", "c_rosa": "demo-rosa"}


def _seed_doc(s, case: Case, name: str) -> Document:
    doc_type, data, extraction = specimens.fixture_for(name)
    doc = docs.store_upload(s, case, doc_type, name, data, uploaded_by="seed", actor_type="system")
    docs.apply_extraction(s, case, doc, {"ok": True, "extractor": "fixture", "data": extraction})
    return doc


def _briefing(s, case: Case, versions: int, queue: list[dict], **extra) -> None:
    for v in range(1, versions + 1):
        body = {"queue": queue if v == versions else [], **(extra if v == versions else {})}
        cs.publish_briefing(s, case, body, proposed_by="case_manager@seed")


def load(reset: bool = True) -> dict[str, str]:
    if reset:
        drop_all()
    create_all()
    specimens.build()
    with session_scope() as s:
        clinic = Clinic(id="cl_valle", name="Clínica Comunitaria del Valle (demo)", is_demo=True,
                        settings={"phone": "(555) 010-0100", "retention": {"transcripts_days": 90,
                                                                           "closed_case_delete_days": 90},
                                  "referral_text": {}, "handles_categories": ["arrest", "removal", "citizenship_claim",
                                                                              "fraud", "danger"]})
        s.add(clinic)
        s.flush()
        pw = auth.hash_password(DEMO_PASSWORD)
        admin = StaffUser(id="su_admin", clinic_id=clinic.id, email="admin@valle.demo", name="Demo Admin",
                          role="admin", password_hash=pw)
        reviewer = StaffUser(id="su_dana", clinic_id=clinic.id, email="dana@valle.demo",
                             name="Dana R. (simulated)", role="reviewer", password_hash=pw)
        intake = StaffUser(id="su_sam", clinic_id=clinic.id, email="sam@valle.demo", name="Sam P.", role="intake",
                           password_hash=pw)
        s.add_all([admin, reviewer, intake])
        # A second clinic, to prove isolation (AT17)
        other = Clinic(id="cl_other", name="Otra Clínica (demo)", is_demo=True, settings={"phone": "(555) 010-0999"})
        s.add(other)
        s.flush()
        s.add(StaffUser(id="su_other", clinic_id=other.id, email="staff@other.demo", name="Other Staff",
                        role="admin", password_hash=pw))
        s.flush()

        def mk(cid, first, last, phone, patient=False):
            c = Case(id=cid, clinic_id=clinic.id, first_name=first, last_name=last, phone=phone,
                     assigned_reviewer=reviewer.id, settings={"patient_mode": patient}, created_by=intake.id,
                     created_at=now())
            s.add(c)
            s.flush()
            cs.emit(s, c, "case.created", {"by": intake.id}, "staff", intake.id)
            auth.issue_link(s, c, LINKS[cid])
            return c

        maria = mk("c_maria", "María", "Torres", "(831) 555-0142")
        jorge = mk("c_jorge", "Jorge", "Ramírez Soto", "(559) 555-0177")
        ana = mk("c_ana", "Ana Lucía", "Hernández Ruiz", "(831) 555-0199")
        rosa = mk("c_rosa", "Rosa", "Delgado Peña", "(831) 555-0123", patient=True)

        # María: three documents already extracted; briefing v3; consent pending
        for n in ("maria_green_card.png", "maria_passport.png", "maria_lease.png"):
            _seed_doc(s, maria, n)
        _briefing(s, maria, 3, [
            {"kind": "ask", "field": "consent", "reason": "consent first"},
            {"kind": "read_back", "field": "lpr_since", "read_value": "document", "reason": "confirm resident-since date"},
            {"kind": "ask", "section": "travel", "field": "trips.any", "reason": "travel next"},
            {"kind": "ask", "section": "addresses", "reason": "then addresses"},
            {"kind": "ask", "section": "employment", "reason": "then employment"},
            {"kind": "ask", "section": "marital", "reason": "then family"},
            {"kind": "ask", "section": "background", "reason": "then background"},
        ], tone_hint="calm, one question at a time")

        # Jorge: consent, eligibility and travel done (as in F1.01–F1.08); in the employment section
        _seed_doc(s, jorge, "jorge_green_card.png")
        simulate_answers(s, jorge, JORGE, actor="seed")
        _briefing(s, jorge, 5, [{"kind": "ask", "section": "employment", "field": "employment[0].employer",
                                 "reason": "employment section"}])

        # Ana Lucía: consent done, no documents, briefing v2
        simulate_answers(s, ana, {"consent": True}, actor="seed")
        _briefing(s, ana, 2, [
            {"kind": "ask", "section": "identity", "field": "names.used", "reason": "identity"},
            {"kind": "ask", "section": "eligibility", "field": "lpr_since", "reason": "eligibility basics"},
            {"kind": "request_upload", "document_type": "green_card", "reason": "no documents on file",
             "text_es": "¿Puede tomar una foto de su tarjeta de residente, por los dos lados? Puede seguir hablando "
                        "conmigo mientras se sube."}])

        # Rosa: patient mode, nothing yet
        _briefing(s, rosa, 1, [])
        for c in (maria, jorge, ana, rosa):
            cs.after_fact_change(s, c)
    base = os.environ.get("ELLIS_PUBLIC_BASE_URL", "http://localhost:5173")
    return {cid: f"{base}/a/{tok}" for cid, tok in LINKS.items()}


if __name__ == "__main__":
    links = load()
    print("Seeded demo clinic. Staff logins (password: ellis-demo): admin@valle.demo, dana@valle.demo, sam@valle.demo")
    for cid, url in links.items():
        print(f"  {cid}: {url}")
