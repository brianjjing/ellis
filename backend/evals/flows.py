"""End-to-end flow evals F1–F4 (Phase 1: stages 0–4), driven through the real liaison, Case API services,
agent runner (skeleton backend) and packet builder.

    ELLIS_TODAY=2026-10-23 uv run python -m evals.flows f1 -v
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from typing import Any

from sqlalchemy import select

from ellis.agents.runner import Runner
from ellis.db import Case, Document, Flag, Packet, ReviewItem, StaffUser, Utterance, session_scope
from ellis.services import case_service as cs
from ellis.services import documents as docs
from ellis.services import review, signoff
from ellis.voice.client import InProcessClient
from ellis.voice.liaison import Liaison
from seed import load as seed_load
from seed import specimens
from seed.scripts import SCRIPTS

from .applicant_sim import SimApplicant, run_conversation

TODAY = date(2026, 10, 23)


class Ctx:
    def __init__(self, case_id: str, verbose: bool = False):
        self.case_id = case_id
        self.verbose = verbose
        self.runner = Runner(debounce_s=0)
        self.runner.dispatch_new_events()
        self.transcript: list[tuple[str, str]] = []

    def p(self, *a):
        if self.verbose:
            print(*a)

    def printer(self, who, x, word=None):
        if not self.verbose:
            return
        if who == "ellis":
            print(("  🔒 " if x.locked else "     ") + "ELLIS:", x.text)
        else:
            print("     USTED:", x, f"   ⟵ barge-in at «{word}»" if word else "")

    def settle(self):
        self.runner.settle()

    def secure(self, field, value):
        with session_scope() as s:
            cs.secure_entry(s, s.get(Case, self.case_id), field, value)

    def biographics(self, vals: dict):
        with session_scope() as s:
            c = s.get(Case, self.case_id)
            for k, v in vals.items():
                cs.secure_entry(s, c, k, v)

    def upload(self, name: str):
        doc_type, data, _ = specimens.fixture_for(name)
        os.environ["ELLIS_EXTRACTION_SYNC"] = "1"
        with session_scope() as s:
            d = docs.store_upload(s, s.get(Case, self.case_id), doc_type, name, data)
            did = d.id
        docs.extract_async(did)
        self.settle()
        self.p(f"     [upload] {name}")
        return did

    def talk(self, sim: SimApplicant, max_turns=200):
        L = Liaison(InProcessClient(self.case_id), today=TODAY)
        self.transcript += run_conversation(L, sim, max_turns=max_turns, on_turn=self.settle, printer=self.printer)
        self.settle()
        return L

    def reviewer_decides(self, decisions: dict[str, tuple[str, str]], staff_id="su_dana") -> list[str]:
        done = []
        with session_scope() as s:
            u = s.get(StaffUser, staff_id)
            items = s.scalars(select(ReviewItem).where(ReviewItem.case_id == self.case_id,
                                                       ReviewItem.status == "open")).all()
            for ri in items:
                d = decisions.get(ri.category) or decisions.get("*")
                if d:
                    review.decide(s, ri, d[0], d[1], u)
                    done.append(f"{ri.category}:{d[0]}")
        self.settle()
        self.p(f"     [reviewer] {done}")
        return done

    def gate(self) -> dict:
        with session_scope() as s:
            return cs.gate_status(s, s.get(Case, self.case_id))

    def mark_ready(self, staff_id="su_dana"):
        with session_scope() as s:
            return review.mark_ready(s, s.get(Case, self.case_id), s.get(StaffUser, staff_id))

    def sign(self, typed_name: str, **kw):
        with session_scope() as s:
            case = s.get(Case, self.case_id)
            version = signoff.ATTESTATION_VERSION[signoff.case_lang(case)]
            return signoff.sign(s, case, typed_name, version, "eval", **kw)

    def state(self) -> str:
        with session_scope() as s:
            return s.get(Case, self.case_id).state


def maria(verbose=False) -> Ctx:
    """F1: consent + barge-in date correction; traffic citation + long absence; sign-off."""
    x = Ctx("c_maria", verbose)
    answers = dict(SCRIPTS["c_maria"])
    sim = SimApplicant(answers, overrides={
        "trips.any": "Sí, una vez, a México, a cuidar a mi mamá. Salí el tres de agosto del 2023.",
        "trips[0].return": "Eh… creo que el tres de marzo… del veinticuatro.",
        "trips[0].home_kept": "Sí, mi esposo y los niños se quedaron.",
        "background.arrested_cited_detained": "Bueno… una vez me dieron una multa por exceso de velocidad, en 2023.",
        "background.detail.citation_year": "En el 2023.",
        "background.detail.citation_county": "En el condado de Monterey.",
        "background.detail.citation_paid": "Ya la pagué.",
        "employment[0].employer": "En una empacadora, Empacadora del Valle.",
        "addresses[0].city": "En Salinas.",
    }, readback_overrides={"trips[0].return": [("¡No, el trece! El trece de marzo.", "tres")]},
        secure=x.secure, biographics=x.biographics)
    x.p("── F1 Session 1 (Fri Oct 23): consent, eligibility, travel correction, intake ──")
    x.talk(sim)
    x.p("── F1.17 Day 3: uploads ──")
    x.upload("maria_court_receipt.png")
    x.upload("maria_tax_2023.png")
    x.p("── F1.18 reviewer queue ──")
    x.reviewer_decides({
        "absence_gt_180": ("clear_with_referral", "Applicant informed a licensed professional can assess continuous "
                                                  "residence; proceeding is her choice."),
        "citation": ("clear", "Speeding ticket, paid; receipt attached."),
    })
    x.p("── F1.19–F1.20 next call: QA questions, changed fields ──")
    x.talk(SimApplicant(answers, secure=x.secure, biographics=x.biographics,
                        overrides={"employment.gap.2019-04-30": "Estaba entre trabajos."}))
    x.p(f"── gate: {x.gate()} ──")
    if x.state() == "review" and x.gate()["passes"]:
        x.mark_ready()
        x.p("── F1.21 sign-off ──")
        out = x.sign("Maria Torres")
        x.p(f"     [signed] packet: {[p['filename'] for p in out['packet']]}")
    return x


def jorge(verbose=False) -> Ctx:
    """F2: stop-now arrest disclosure while explaining an employment gap."""
    x = Ctx("c_jorge", verbose)
    answers = dict(SCRIPTS["c_jorge"])
    with session_scope() as s:
        c = s.get(Case, "c_jorge")
        cs.publish_briefing(s, c, {"queue": [{"kind": "ask", "field": "employment.gap.2016-03",
                                              "question_es": "¿Trabajó entre marzo y septiembre de 2016?",
                                              "reason": "employment gap"}]}, "case_manager@eval")
    sim = SimApplicant(answers, secure=x.secure, biographics=x.biographics, overrides={
        "employment.gap.2016-03": "No, esos meses no, porque me arrestaron por una pelea, pero después no pasó nada…",
        "__after_stop__": ["Pero no me condenaron. ¿Eso importa?", "Está bien, sigamos."],
    })
    x.p("── F2 session: the disclosure ──")
    x.talk(sim)
    x.p("── F2.08 professional draft (criminal-history block blank) ──")
    with session_scope() as s:
        c = s.get(Case, "c_jorge")
        p = signoff.professional_draft(s, c)
        x.p(f"     [draft] {p.filename}")
        x.p("── F2.09 'My professional will file for me' → referred_out / prep_only ──")
        c.sub_mode = "prep_only"
        cs.set_state(s, c, "referred_out", "applicant reports representation", "applicant", "applicant")
    x.reviewer_decides({"arrest": ("resolved_by_professional", "Applicant reports representation.")})
    return x


def ana(verbose=False) -> Ctx:
    """F3: document conflict (2019 vs 2020-06-02), glare retake, name mismatch, name change."""
    x = Ctx("c_ana", verbose)
    answers = dict(SCRIPTS["c_ana"])
    uploads = iter(["ana_green_card_glare.png", "ana_green_card_clear.png"])

    def upload(_text):
        n = next(uploads, None)
        if n:
            x.upload(n)
    sim = SimApplicant(answers, secure=x.secure, biographics=x.biographics, upload=upload, overrides={
        "lpr_since": "Desde junio del 2019, creo.",
        "name.given": "Ana Lucía",
        "name.family": "Morales… bueno, en mis papeles todavía dice Hernández Ruiz.",
        "names.used": "Sí, Ana Lucía Morales.",
        "name_change.requested": "Sí: Ana Lucía Morales.",
        "spouse.name": "Daniel Morales",
        "spouse.marriage_date": "El quince de abril de 2023",
    }, readback_overrides={"lpr_since": ["No estoy segura.", "Ah, sí, 2020. Lo de 2019 fue la entrevista."]})
    x.p("── F3 session: upload during the call ──")
    x.talk(sim)
    x.upload("ana_marriage_certificate.png")
    x.upload("ana_passport.png")
    x.talk(SimApplicant(answers, secure=x.secure, biographics=x.biographics))
    x.p("── F3.11 reviewer ──")
    x.reviewer_decides({
        "name_mismatch": ("clear", "Current legal name per documents; name change requested on the form."),
        "other_path": ("clear", "Proceeding on the 5-year path; the applicant can discuss the 3-year path with us."),
        "date_conflict": ("clear", "Resolved: document date confirmed by the applicant."),
    })
    x.talk(SimApplicant(answers, secure=x.secure, biographics=x.biographics))
    x.p(f"── gate: {x.gate()} ──")
    if x.state() == "review" and x.gate()["passes"]:
        x.mark_ready()
        out = x.sign("Ana Lucía Hernández Ruiz")
        x.p(f"     [signed] packet: {[p['filename'] for p in out['packet']]}")
    return x


def rosa(verbose=False) -> Ctx:
    """F4: 55/15 exemption, family member present, tax flag, fee waiver, paper packet."""
    x = Ctx("c_rosa", verbose)
    answers = dict(SCRIPTS["c_rosa"])
    answers.update({"lpr_since": "2008-03-10", "dob": "1965-02-14"})
    sim = SimApplicant(answers, secure=x.secure, biographics=x.biographics, overrides={
        "__third_party__": ["Sí, soy su hija."],
        "background.tax_not_filed": "En 2022 no hice los impuestos, gané muy poquito.",
        "fee.benefit_type": "Tengo Medi-Cal.",
    })
    x.p("── F4 session: family member present ──")
    x.talk(sim)
    x.upload("rosa_green_card.png")
    x.upload("rosa_benefit_letter.png")
    x.upload("rosa_irs_2022.png")
    x.p("── F4.08 reviewer ──")
    x.reviewer_decides({"taxes": ("clear_with_referral", "Applicant pointed to free tax help (IRS VITA); a "
                                                         "professional can assess. Fee path: applicant chooses I-912."),
                        "*": ("clear", "Reviewed.")})
    x.talk(SimApplicant(answers, secure=x.secure, biographics=x.biographics))
    x.p(f"── gate: {x.gate()} ──")
    if x.state() == "review" and x.gate()["passes"]:
        x.mark_ready()
        out = x.sign("Rosa Delgado Peña", read_aloud=True, assisted_by="daughter")
        x.p(f"     [signed] packet: {[p['filename'] for p in out['packet']]}")
    return x


FLOWS = {"f1": maria, "f2": jorge, "f3": ana, "f4": rosa}


# Planted issues per flow (success metric: planted-issue recall 100%, false alarms reported).
PLANTED = {"f1": {"absence_gt_180", "date_conflict", "citation"}, "f2": {"arrest"},
           "f3": {"name_mismatch", "date_conflict"}, "f4": {"taxes"}}
NOT_EXPECTED = {"f4": {"absence_gt_180", "absence_gte_365", "presence_short"}}


def metrics(name: str, case_id: str) -> dict:
    with session_scope() as s:
        cats = {f.category for f in s.scalars(select(Flag).where(Flag.case_id == case_id))}
        turns = len(s.scalars(select(Utterance).where(Utterance.case_id == case_id,
                                                      Utterance.speaker == "applicant")).all())
    planted = PLANTED[name]
    found = planted & cats
    false_alarms = sorted((cats - planted) & NOT_EXPECTED.get(name, set()))
    return {"planted": sorted(planted), "found": sorted(found), "recall": len(found) / len(planted),
            "false_alarms": false_alarms, "all_flags": sorted(cats), "applicant_turns": turns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flow", choices=sorted(FLOWS) + ["all"])
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    os.environ.setdefault("ELLIS_TODAY", TODAY.isoformat())
    seed_load.load()
    for name in (sorted(FLOWS) if a.flow == "all" else [a.flow]):
        x = FLOWS[name](a.verbose)
        g = x.gate()
        m = metrics(name, x.case_id)
        print(f"{name}: state={x.state()} gate={'passes' if g['passes'] else [f['code'] for f in g['failing']]} "
              f"planted-issue recall={m['recall']:.0%} false_alarms={m['false_alarms']} flags={m['all_flags']}")
        if g["failing"] and a.verbose:
            for f in g["failing"]:
                print("   ", f)


if __name__ == "__main__":
    sys.exit(main())
