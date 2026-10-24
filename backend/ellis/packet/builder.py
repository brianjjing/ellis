"""Packet builder: deterministic form filler + generated pages (reportlab).

Real identifiers are inserted from the vault here and only here (n400_draft.pdf, i912_draft.pdf).
Footer on every page: "Prepared with Ellis; review before signing."
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import fee_config, settings, yaml_config
from ..db import Case, Clinic, Document, Memo, Packet, ReviewItem, Signoff, now
from ..rules import engine as rules
from ..services import case_service as cs
from ..services import catalog
from ..services.values import display_value

FOOTER = "Prepared with Ellis; review before signing. Ellis never files: the applicant or the clinic submits to USCIS."


class Pdf:
    def __init__(self, path: Path, title: str, subtitle: str = ""):
        self.c = canvas.Canvas(str(path), pagesize=letter)
        self.c.setTitle(title)
        self.w, self.h = letter
        self.title, self.subtitle = title, subtitle
        self.page = 0
        self._new_page()

    def _new_page(self):
        if self.page:
            self.c.showPage()
        self.page += 1
        self.y = self.h - 0.75 * inch
        self.c.setFont("Helvetica-Bold", 14)
        self.c.drawString(0.75 * inch, self.y, self.title)
        self.y -= 16
        if self.subtitle:
            self.c.setFont("Helvetica", 9)
            self.c.drawString(0.75 * inch, self.y, self.subtitle)
            self.y -= 14
        self.c.setFont("Helvetica", 8)
        self.c.drawString(0.75 * inch, 0.5 * inch, FOOTER)
        self.c.drawRightString(self.w - 0.75 * inch, 0.5 * inch, f"Page {self.page}")
        self.y -= 8

    def need(self, dy: float):
        if self.y - dy < 0.9 * inch:
            self._new_page()

    def heading(self, text: str):
        self.need(30)
        self.y -= 8
        self.c.setFont("Helvetica-Bold", 11)
        self.c.drawString(0.75 * inch, self.y, text)
        self.y -= 4
        self.c.line(0.75 * inch, self.y, self.w - 0.75 * inch, self.y)
        self.y -= 14

    def row(self, label: str, value: str, note: str = ""):
        lines = _wrap(value, 60) or [""]
        self.need(14 * len(lines) + (10 if note else 0))
        self.c.setFont("Helvetica", 9)
        for ln in _wrap(label, 48)[:2]:
            self.c.drawString(0.75 * inch, self.y, ln)
            break
        self.c.setFont("Helvetica-Bold", 9)
        for i, ln in enumerate(lines):
            self.c.drawString(3.9 * inch, self.y - 12 * i, ln)
        self.y -= 12 * len(lines)
        if note:
            self.c.setFont("Helvetica-Oblique", 7)
            self.c.drawString(3.9 * inch, self.y, note[:110])
            self.y -= 10
        self.y -= 2

    def para(self, text: str, size: int = 9):
        self.c.setFont("Helvetica", size)
        for ln in _wrap(text, 105):
            self.need(13)
            self.c.drawString(0.75 * inch, self.y, ln)
            self.y -= 12
        self.y -= 4

    def save(self):
        self.c.save()


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def _provenance(f) -> str:
    if f is None:
        return ""
    if f.source == "document":
        return f"from document {f.provenance.get('document_type', '')} ({f.provenance.get('document_id', '')})"
    if f.provenance.get("simulated"):
        return "simulated demo answer"
    src = {"spoken": "spoken", "applicant_typed": "typed by applicant", "staff_typed": "typed by staff",
           "derived": "rules engine"}.get(f.source, f.source)
    extra = f", matches {f.matches_document}" if f.matches_document else ""
    return f"{src}, {f.status}{extra}"


def _fields_for_part(part: dict, cur: dict) -> list[str]:
    keys = list(part.get("fields", []))
    if "list" in part:
        name = part["list"]
        keys += sorted([k for k in cur if k.startswith(f"{name}[")],
                       key=lambda k: (int(k.split("[")[1].split("]")[0]), k))
    if "prefix" in part:
        keys += [k for k in catalog._static() if k.startswith(part["prefix"])]
    return keys


def _value(s: Session, case: Case, key: str, cur: dict, real: bool) -> str:
    f = cur.get(key)
    if f is None:
        return "—"
    if catalog.is_masked(key):
        if real:
            v = cs.vault_lookup(s, f.id)
            return v or "—"
        last4 = cs.vault_last4(s, f.id)
        return f"•••• {last4}" if last4 else catalog.mask_token(key)
    return display_value(key, f.value)


def build_packet(s: Session, case: Case, signoff: Signoff | None, kinds: list[str] | None = None) -> list[Packet]:
    clinic = s.get(Clinic, case.clinic_id)
    folder = settings.files_dir / case.id / "packet"
    folder.mkdir(parents=True, exist_ok=True)
    cur = cs.current_facts(s, case.id)
    fact_versions = sorted(f.id for f in cur.values())
    der = cs.latest_derived(s, case.id)
    nf = yaml_config("n400_fields.yaml")
    sub = f"{case.first_name} {case.last_name} · case {case.id} · {clinic.name} · built {now().date().isoformat()}"
    vals = {k: f.value for k, f in cur.items()}
    fee_res = None
    if vals.get("fee.method"):
        try:
            fee_res = rules.fee(vals["fee.method"], vals.get("fee.benefit_type"),
                                int(vals["fee.household_size"]) if vals.get("fee.household_size") else None,
                                cs.real_value(s, case.id, "fee.income") and int(cs.real_value(s, case.id, "fee.income")),
                                cs.today(), fee_config())
        except Exception:  # noqa: BLE001
            fee_res = None
    waiver = bool(fee_res and (fee_res.get("form") == "I-912" or (fee_res.get("paper_option") or {}).get("form") == "I-912")
                  and vals.get("fee.method") == "paper")
    kinds = kinds or ["n400_pdf", "online_copy_sheet", "evidence_index", "fee_sheet", "filing_checklist",
                      "reviewer_summary"] + (["i912_pdf"] if waiver else [])
    out: list[Packet] = []
    for kind in kinds:
        path = folder / f"{kind}.pdf"
        fn = {
            "n400_pdf": "n400_draft.pdf", "online_copy_sheet": "online_copy_sheet.pdf",
            "evidence_index": "evidence_index.pdf", "fee_sheet": "fee_sheet.pdf",
            "filing_checklist": "filing_checklist.pdf", "reviewer_summary": "reviewer_summary.pdf",
            "i912_pdf": "i912_draft.pdf", "professional_draft": "professional_draft.pdf",
        }[kind]
        path = folder / fn
        if kind == "n400_pdf":
            p = Pdf(path, "Form N-400 — DRAFT for review (not the official form)", sub)
            p.para(f"Form edition: {nf['edition']}. TODO(open-question-1): copy answers into the official form "
                   "edition after it is verified on uscis.gov.")
            for part in nf["parts"]:
                p.heading(part["title"])
                if part.get("note"):
                    p.para(part["note"])
                for key in _fields_for_part(part, cur):
                    p.row(catalog.label_en(key), _value(s, case, key, cur, real=True), _provenance(cur.get(key)))
            p.save()
        elif kind == "professional_draft":
            p = Pdf(path, "Draft for your licensed professional (not the official form)", sub)
            p.para("All confirmed answers with provenance. The criminal-history block is blank: it is completed "
                   "with your licensed professional, outside Ellis.")
            for part in nf["parts"]:
                p.heading(part["title"])
                for key in _fields_for_part(part, cur):
                    f = cur.get(key)
                    if f is not None and f.value == catalog.DEFERRED:
                        p.row(catalog.label_en(key), "[BLANK — to be completed with your licensed professional]")
                        continue
                    p.row(catalog.label_en(key), _value(s, case, key, cur, real=False), _provenance(f))
            p.save()
        elif kind == "online_copy_sheet":
            p = Pdf(path, "Online copy sheet — answers in online-form order", sub)
            p.para("Type these answers into your own USCIS online account. Sensitive numbers are shown masked; "
                   "use your own documents for them. Ellis does not file for you.")
            order = nf["online_order"]
            p.heading("Answers")
            for item in order:
                keys = ([k for k in catalog._static() if k.startswith(item)] if item.endswith(".")
                        else sorted([k for k in cur if k.startswith(item + "[")]) if item in catalog.lists()
                        else [item])
                for key in keys:
                    if key in cur:
                        p.row(catalog.label_en(key), _value(s, case, key, cur, real=False))
            p.save()
        elif kind == "evidence_index":
            p = Pdf(path, "Evidence index", sub)
            docs = list(s.scalars(select(Document).where(Document.case_id == case.id, Document.status == "extracted")
                                  .order_by(Document.ts)))
            p.heading("Exhibits")
            for i, d in enumerate(docs):
                letter_ = d.exhibit or chr(ord("A") + i)
                supports = ", ".join(d.checks.get("supports", []) or d.checks.get("applied_fields", [])) or "case evidence"
                p.row(f"Exhibit {letter_}: {d.document_type.replace('_', ' ')}",
                      f"quality {d.quality}; supports {supports}", d.filename)
            p.save()
        elif kind == "fee_sheet":
            p = Pdf(path, "Fee sheet", sub)
            if fee_res:
                p.row("Filing method", str(vals.get("fee.method")))
                p.row("Amount", f"${fee_res.get('amount')}")
                if fee_res.get("form"):
                    p.row("Form", fee_res["form"])
                if fee_res.get("paper_option"):
                    po = fee_res["paper_option"]
                    p.row("Paper-only option", f"${po['amount']} {po.get('form') or ''}")
                p.row("Fee table version", fee_res["fee_table_version"])
                p.row("Rule", fee_res["rule_id"])
                for w in fee_res.get("watch", []):
                    p.para("Watch item (information, not advice): " + w)
            else:
                p.para("No filing method recorded.")
            p.save()
        elif kind == "filing_checklist":
            p = Pdf(path, "Filing checklist", sub)
            method = vals.get("fee.method")
            if method == "paper":
                items = ["Print every page single-sided.", "Sign the N-400 in black ink.",
                         "Include copies of your green card, front and back."]
                if waiver:
                    items += ["Sign the I-912 in black ink.", "Include a copy of your benefit letter."]
                items += ["Check the current filing address on uscis.gov (Ellis does not hard-code it).",
                          "Mail it yourself, or ask your clinic to file for you."]
            else:
                items = ["Sign in to your own USCIS online account.", "Type the answers from the online copy sheet.",
                         "Upload copies of your green card, front and back.", "Pay the fee shown on the fee sheet.",
                         "Ellis never files: you or your clinic submit to USCIS."]
            p.heading("Steps")
            for it in items:
                p.para("☐  " + it)
            p.save()
        elif kind == "i912_pdf":
            p = Pdf(path, "Form I-912 — DRAFT for review (not the official form)", sub)
            p.para("Request for fee waiver. Waiver criteria are NEEDS EXPERT CHECK (open question 9).")
            p.row("Applicant", f"{vals.get('name.given', case.first_name)} {vals.get('name.family', case.last_name)}")
            p.row("A-number", _value(s, case, "a_number", cur, real=True))
            p.row("Means-tested benefit", str(vals.get("fee.benefit_type") or "—"))
            p.row("Household size", str(vals.get("fee.household_size") or "—"))
            p.row("Household income", str(cs.real_value(s, case.id, "fee.income") or "—"))
            p.save()
        elif kind == "reviewer_summary":
            p = Pdf(path, "Reviewer summary (for the clinic)", sub)
            p.heading("Review decisions")
            for ri in s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id).order_by(ReviewItem.ts)):
                p.row(f"{ri.category} · {ri.speed}", f"{ri.decision or 'open'}: {ri.decision_note or ''}",
                      ri.facts_summary or "")
            qa = s.scalars(select(Memo).where(Memo.case_id == case.id, Memo.kind == "qa").order_by(Memo.ts.desc())).first()
            p.heading("QA memo")
            p.para(qa.body_md if qa else "No QA memo.")
            if der:
                p.heading("Rules engine")
                p.row("Rule config", der.rule_config_version)
                for k in ("earliest_filing", "presence_days", "civics_version"):
                    if k in der.data:
                        p.row(k, str(der.data[k]))
            p.save()
        data = path.read_bytes()
        pk = Packet(clinic_id=case.clinic_id, case_id=case.id, kind=kind, filename=fn, storage_path=str(path),
                    sha256=hashlib.sha256(data).hexdigest(), built_from_fact_versions=fact_versions,
                    signoff_id=signoff.id if signoff else None, ts=now())
        s.add(pk)
        out.append(pk)
    s.flush()
    cs.emit(s, case, "packet.built", {"kinds": kinds, "signoff_id": signoff.id if signoff else None})
    return out
