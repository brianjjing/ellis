"""Deterministic skeleton staff agents. Same inputs (context) and outputs (proposal items) as the model-backed
agents, so each can be swapped for a Creao or Claude agent without touching the Case API.

They read only the masked context, never compute dates themselves (dates come from `derived`), and propose.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ..extraction.schemas import LABELS_EN, LABELS_ES
from ..rules import engine as rules
from ..services import catalog

MONTHS_ES = rules.MONTHS_ES
MONTHS_EN = rules.MONTHS_EN


def _facts(ctx) -> dict[str, Any]:
    return {k: v["value"] for k, v in ctx["facts"].items()}


def _flags(ctx, cat: str | None = None) -> list[dict]:
    return [f for f in ctx["open_flags"] if f.get("speed") != "stop_now" and (cat is None or f.get("category") == cat)]


def _docs(ctx, doc_type: str, min_quality: tuple = ("high", "medium")) -> list[dict]:
    return [d for d in ctx["documents"] if d["document_type"] == doc_type and d["status"] == "extracted"
            and d["quality"] in min_quality]


def _trigger_kinds(ctx) -> set[str]:
    return {e["kind"] for e in ctx.get("trigger_events", [])}


# ------------------------------------------------------------------------------------------- case manager

def case_manager(ctx: dict) -> list[dict]:
    # title_es/question_es fields below hold pre-resolved text in this case's language (not necessarily
    # Spanish); team_cards() and the liaison's task-reading loop just display/relay it as-is.
    lang = ctx.get("language", "es")
    items: list[dict] = []
    facts = ctx["facts"]
    queue: list[dict] = []
    reasons: list[str] = []
    # title_es/question_es fields below hold pre-resolved text in this case's language (not necessarily
    # Spanish); team_cards() and the case_manager task-reading loop just display/relay it as-is.
    lang = ctx.get("language", "en")
    # 1. read back hedged / conflicting / disputed / third-party values first
    conflict_fields = {f["field"] for f in _flags(ctx, "date_conflict") if f.get("field")}
    for k, v in facts.items():
        if v["value"] == catalog.DEFERRED or v["status"] == "confirmed":
            continue
        if catalog.is_masked(k):
            continue
        d = catalog.field_def(k) or {}
        if d.get("capture") in ("S", "P", "E"):
            continue
        why = None
        if k in conflict_fields and v.get("hedge"):
            why = "hedged answer conflicts with a document"
        elif k in conflict_fields:
            why = "answer conflicts with a document"
        elif v.get("conflict"):
            why = "two different answers; confirm one"
        elif v.get("third_party"):
            why = "answered by a family member; confirm with the applicant"
        elif v["source"] == "document" and d.get("document_authoritative") and _has_spoken_dispute(ctx, k):
            why = "document outranks recall; confirm the document value"
        elif v.get("hedge") and catalog.is_date_field(k):
            why = "hedged date"
        if why:
            m = catalog.LIST_RE.match(k)
            read_value = "applicant" if m and m["list"] == "trips" else (
                "document" if d.get("document_authoritative") else "applicant")
            queue.append({"kind": "read_back", "field": k, "read_value": read_value, "reason": why})
            reasons.append(f"read back {k} first ({why})")
    # 2. low-quality uploads: ask for a retake
    for d in ctx["documents"]:
        if d["status"] == "extracted" and d["quality"] == "low":
            newer = [x for x in ctx["documents"] if x["document_type"] == d["document_type"]
                     and x["uploaded_at"] > d["uploaded_at"]]
            if not newer:
                label_es = LABELS_ES.get(d["document_type"], "documento")
                label_en = LABELS_EN.get(d["document_type"], "document")
                rs = d.get("quality_reasons") or []
                why_es = "con reflejo en las fechas" if "glare" in rs else "borrosa" if "blurry" in rs else "incompleta"
                why_en = "has glare over the dates" if "glare" in rs else "blurry" if "blurry" in rs else "incomplete"
                queue.insert(0, {"kind": "request_upload", "document_type": d["document_type"],
                                 "text_es": f"La foto de su {label_es} salió {why_es}. ¿Puede tomar otra, con el "
                                            f"documento sobre una mesa?",
                                 "text_en": f"The photo of your {label_en} {why_en}. Can you take another one, "
                                            f"with the document on a table?",
                                 "reason": "retake needed"})
                reasons.append(f"ask for a retake of {d['document_type']}")
    # 3. reviewer "needs more info" and QA challenges that carry a question
    # Task.question_es holds pre-resolved text in whatever language it was proposed in (qa_reviewer writes
    # it in ctx["language"]); store it under the matching dynamic key so _ask() picks it up regardless of
    # language instead of silently falling back to a generic templated question.
    for t in ctx["tasks"]:
        if t["status"] == "open" and t.get("question_es") and t.get("field") and t["field"] not in facts:
            queue.append({"kind": "ask", "field": t["field"], f"question_{lang}": t["question_es"],
                          "reason": f"{t['agent']} {t['kind']}"})
            reasons.append(f"ask {t['field']} for {t['agent']}")
    # 4. documents still needed
    for g in ctx["gaps"]:
        if g["status"] == "open":
            queue.append({"kind": "request_upload", "document_type": g["document_type"], "reason": g["key"]})
    # 5. fee follow-ups for a paper waiver / reduced fee
    fv = _facts(ctx)
    if fv.get("fee.method") == "paper" and fv.get("fee.benefit_type") and "fee.income" not in fv:
        queue.append({"kind": "request_secure_entry", "field": "fee.household_size", "reason": "fee waiver"})
        queue.append({"kind": "request_secure_entry", "field": "fee.income", "reason": "fee waiver"})
    if fv.get("fee.method") == "paper" and "fee.benefit_type" not in fv:
        queue.append({"kind": "ask", "field": "fee.benefit_type", "reason": "possible fee waiver"})
    # 6. keep the section order the coordinator chose earlier, for sections that still have work
    req = catalog.fallback_queue(facts, ctx.get("derived"), date.fromisoformat(ctx["today"]))
    open_sections = {it.get("section") for it in req}
    for it in (ctx.get("last_briefing") or {}).get("queue", []):
        if it.get("field") == "consent" or it in queue:
            continue
        if it.get("kind") == "read_back" and it.get("field"):
            f = facts.get(it["field"])
            if f is not None and f["status"] != "confirmed" and not any(q.get("field") == it["field"] for q in queue):
                queue.insert(0, it)
            continue
        if it.get("kind") != "ask":
            continue
        if (it.get("field") and it["field"] not in facts) or (not it.get("field") and it.get("section") in open_sections):
            queue.append(it)
    tone = None
    if any(v.get("hedge") for k, v in facts.items() if catalog.is_date_field(k)):
        tone = "go slower on dates; one field per sentence"
    if ctx["case"]["patient_mode"]:
        tone = "short sentences; repeat on request; slow pace"
    visible = sorted({f["category"] for f in _flags(ctx) if f["category"] in
                      ("absence_gt_180", "absence_gte_365", "citation", "taxes", "name_mismatch")})
    notes = [r["decision_note"] for r in ctx["review_items"] if r.get("decision") == "clear_with_referral"
             and r.get("decision_note")]
    done = [p for p in _progress(ctx) if p[1] == "done"]
    close = {"sections_done": [catalog.section_label(sec).lower() for sec, _ in done if sec != "consent"][-4:],
             "next_items": [g["label_es"] for g in ctx["gaps"] if g["status"] == "open" and g.get("label_es")][:3]}
    if ctx.get("deferred_sections"):
        close["next_items"] = close["next_items"] + ["revisión pendiente con su profesional"]
    items.append({"type": "briefing", "payload": {"queue": queue[:12], "tone_hint": tone,
                                                  "applicant_visible_flags": visible,
                                                  "reviewer_notes_for_applicant": notes, "session_close": close}})
    if reasons:
        items.append({"type": "task", "payload": {"kind": "finding", "title": "Briefing: " + "; ".join(reasons[:3]),
                                                  "title_es": "Ordered the following questions" if lang == "en"
                                                              else "Ordenó las siguientes preguntas"}})
    # other paths are flagged for the reviewer, never computed (Phase 1 = 5-year path)
    if fv.get("spouse.citizenship_status") == "us_citizen" and fv.get("spouse.marriage_date") and \
            fv.get("marital.status") == "married":
        items.append({"type": "review_item", "payload": {
            "category": "other_path", "field": "spouse.citizenship_status",
            "note": "Married to a U.S. citizen: a 3-year path may exist. Phase 1 prepares the 5-year path only; "
                    "a reviewer decides (NEEDS EXPERT CHECK)."}})
    # status memo (internal)
    items.append({"type": "memo", "payload": {"kind": "status", "body_md": _status_memo(ctx)}})
    return items


def _has_spoken_dispute(ctx, field: str) -> bool:
    return bool(ctx["facts"].get(field, {}).get("conflict"))


def _progress(ctx) -> list[tuple[str, str]]:
    req = catalog.required_fields(ctx["facts"], ctx.get("derived"), date.fromisoformat(ctx["today"]))
    out = []
    for sec in catalog.sections():
        keys = [k for k in req if catalog.section_of(k) == sec["key"]]
        if not keys:
            continue
        conf = [k for k in keys if ctx["facts"].get(k, {}).get("status") == "confirmed"]
        out.append((sec["key"], "done" if len(conf) == len(keys) else "partial" if conf else "not_started"))
    return out


def _status_memo(ctx) -> str:
    lines = [f"**State:** {ctx['case']['state']}", ""]
    miss = ctx["missing_required"]
    lines.append(f"**Required fields without a fact:** {len(miss)}" + (f" (next: {', '.join(miss[:5])})" if miss else ""))
    fl = _flags(ctx)
    if fl:
        lines.append("**Open flags:** " + ", ".join(f"{f['category']} ({f.get('field') or '—'})" for f in fl))
    stops = [f for f in ctx["open_flags"] if f.get("speed") == "stop_now"]
    if stops:
        lines.append(f"**Stop-now:** {len(stops)} section(s) referred to a licensed professional "
                     f"({', '.join(sorted({f['section'] for f in stops}))}). The case cannot reach ready until "
                     "professional review is recorded.")
    gaps = [g for g in ctx["gaps"] if g["status"] == "open"]
    if gaps:
        lines.append("**Documents still needed:** " + ", ".join(g["key"] for g in gaps))
    failing = [f["code"] for f in ctx["gate"]["failing"]]
    lines.append("**Gate:** " + ("passes" if not failing else "blocked by " + ", ".join(failing)))
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------- doc paralegal

# (document_type, reason [clinic-facing, always English], label_es, label_en [applicant-facing gap text])
GAP_RULES = {
    "citation": ("court_record", "Court disposition or proof of payment for the citation",
                 "Recibo o documento de la corte de su multa", "Court record or proof of payment for your citation"),
    "taxes": ("tax_transcript", "IRS account transcript for the year in question (shows whether a return is on file)",
              "Comprobante de impuestos del IRS", "IRS tax transcript"),
    "name_mismatch": ("marriage_certificate", "Marriage certificate (marital and name history)",
                      "Acta de matrimonio", "Marriage certificate"),
}


def doc_paralegal(ctx: dict) -> list[dict]:
    lang = ctx.get("language", "en")
    items: list[dict] = []
    fv = _facts(ctx)
    today = date.fromisoformat(ctx["today"])
    gaps = {g["key"]: g for g in ctx["gaps"]}
    # checklist per document
    exhibit = 0
    for d in ctx["documents"]:
        if d["status"] != "extracted":
            continue
        x = d.get("extraction") or {}
        checks: dict[str, Any] = {"legible": d["quality"] != "low", "correct_type": True,
                                  "quality": d["quality"], "quality_reasons": d.get("quality_reasons", [])}
        if d["document_type"] == "green_card":
            checks["both_sides"] = x.get("side") in ("both", None)
            exp = x.get("card_expires")
            if exp:
                try:
                    checks["not_expired"] = date.fromisoformat(exp) >= today
                except ValueError:
                    pass
        checks["belongs_to_applicant"] = d.get("checks", {}).get("belongs_to_applicant", True)
        supports = _supports(d, fv)
        checks["supports"] = supports
        ex = None
        if d["quality"] in ("high", "medium") and checks["belongs_to_applicant"]:
            exhibit += 1
            ex = chr(ord("A") + exhibit - 1)
        items.append({"type": "doc_checks", "payload": {"document_id": d["id"], "checks": checks, "exhibit": ex}})
        if d["quality"] == "low":
            label = LABELS_EN.get(d["document_type"], "document") if lang == "en" else LABELS_ES.get(d["document_type"], "documento")
            title_es = f"Asked for another photo of your {label}" if lang == "en" else f"Pidió otra foto de su {label}"
            items.append({"type": "task", "payload": {
                "kind": "finding", "title": f"{d['document_type']} — retake needed ({', '.join(d.get('quality_reasons') or ['low quality'])})",
                "title_es": title_es}})
        elif d["document_type"] != "other":
            label = LABELS_EN.get(d["document_type"], "document") if lang == "en" else LABELS_ES.get(d["document_type"], "documento")
            title_es = f"Checked your {label}" if lang == "en" else f"Revisó su {label}"
            items.append({"type": "task", "payload": {
                "kind": "finding", "title": f"Checked {d['document_type']} ({d['quality']}): {', '.join(supports) or 'on file'}",
                "title_es": title_es}})
    # gaps from open flags (never for stop-now sections). wanted[key] = (document_type, reason [clinic,
    # English], label_es, label_en); the loop below picks the label matching this case's language.
    wanted: dict[str, tuple[str, str, str, str]] = {}
    if not _docs(ctx, "green_card", ("high",)):
        wanted["base:green_card"] = ("green_card", "Green card, front and back",
                                     "Foto de su tarjeta de residente (los dos lados)",
                                     "Photo of your green card (both sides)")
    for f in _flags(ctx):
        cat = f["category"]
        if cat in GAP_RULES:
            wanted[f"flag:{cat}:{f.get('field') or ''}"] = GAP_RULES[cat]
        if cat in ("absence_gt_180", "absence_gte_365"):
            m = catalog.LIST_RE.match(f.get("field") or "")
            i = m["i"] if m else "0"
            dep = fv.get(f"trips[{i}].departure") or ""
            year = dep[:4] if dep else ""
            lease = _docs(ctx, "lease")
            note = "lease already on file covers it; " if lease else ""
            wanted[f"flag:{cat}:{f.get('field')}"] = (
                "tax_transcript", f"Proof home was kept during trip {int(i) + 1}: {note}consider the {year} tax return",
                f"Comprobante de impuestos de {year}" if year else "Comprobante de impuestos",
                f"{year} tax transcript" if year else "Tax transcript")
    if fv.get("fee.method") == "paper" and fv.get("fee.benefit_type"):
        wanted["fee:benefit_letter"] = ("benefit_letter", "Current benefit letter for the fee waiver",
                                        "Carta de beneficios de este año", "This year's benefit letter")
    have = {(g["document_type"], g.get("label_es")) for g in gaps.values()}
    for key, (dt, reason, label_es, label_en) in wanted.items():
        label = label_en if lang == "en" else label_es
        if key not in gaps and (dt, label) not in have:
            have.add((dt, label))
            items.append({"type": "gap", "payload": {"document_type": dt, "reason": reason, "label_es": label,
                                                     "key": key}})
            title_es = f"Added to the list: {label}" if lang == "en" else f"Agregó a la lista: {label}"
            items.append({"type": "task", "payload": {"kind": "finding", "title": f"Gap: {reason}",
                                                      "title_es": title_es}})
    # close gaps when a usable document of that type arrives
    for key, g in gaps.items():
        if g["status"] != "open":
            continue
        docs = _docs(ctx, g["document_type"], ("high", "medium"))
        if g["document_type"] == "green_card":
            docs = _docs(ctx, "green_card", ("high",))
        if docs:
            items.append({"type": "gap_close", "payload": {"key": key, "document_id": docs[-1]["id"]}})
    # attach evidence to review items
    attach = {"absence_gt_180": ["lease", "tax_transcript"], "absence_gte_365": ["lease", "tax_transcript"],
              "citation": ["court_record"], "taxes": ["tax_transcript"],
              "name_mismatch": ["marriage_certificate", "passport", "green_card"]}
    for r in ctx["review_items"]:
        if r.get("status") != "open" or "category" not in r:
            continue
        for dt in attach.get(r["category"], []):
            for d in _docs(ctx, dt):
                if d["id"] not in (r.get("evidence") or []):
                    items.append({"type": "evidence", "payload": {"category": r["category"], "field": r.get("field"),
                                                                  "document_id": d["id"]}})
    return items


def _supports(d: dict, fv: dict) -> list[str]:
    t = d["document_type"]
    x = d.get("extraction") or {}
    return {
        "green_card": ["identity", "resident since", "A-number"],
        "passport": ["identity", "travel"] + (["entry stamps"] if x.get("stamps") else []),
        "lease": ["address history", "ties during absence"],
        "court_record": ["citation disposition"],
        "tax_transcript": [f"tax year {x.get('tax_year')}"] if x.get("tax_year") else ["taxes"],
        "marriage_certificate": ["marital history", "name history"],
        "benefit_letter": ["fee waiver"],
    }.get(t, [])


# ------------------------------------------------------------------------------------------- docketing clerk

def docketing_clerk(ctx: dict) -> list[dict]:
    lang = ctx.get("language", "en")
    title_es = "Reviewed the dates of your case" if lang == "en" else "Revisó las fechas de su caso"
    items: list[dict] = []
    der = ctx.get("derived") or {}
    current = {d["kind"]: d for d in ctx["deadlines"]}
    changed = False
    if der.get("earliest_filing"):
        if current.get("filing_window_opens", {}).get("date") != der["earliest_filing"]:
            changed = True
        items.append({"type": "deadline", "payload": {"kind": "filing_window_opens", "date_from_rule": "R-ELIG-EARLY",
                                                      "note": "earliest filing date (rules engine)"}})
        items.append({"type": "deadline", "payload": {"kind": "five_year_anniversary", "date_from_rule": "R-ANNIV",
                                                      "note": "5-year LPR anniversary"}})
    fee_watch = "DHS proposed fee rule (June 2026): would raise fees and end reduced fee and waivers; not in effect"
    items.append({"type": "deadline", "payload": {"kind": "watch:fee_rule", "note": fee_watch}})
    if ctx["case"]["state"] == "signed":
        items.append({"type": "task", "payload": {
            "kind": "finding", "title": "Information: file before the proposed fee rule takes effect, if it is "
                                        "finalized (not urging; effective-date treatment NEEDS EXPERT CHECK)",
            "title_es": title_es}})
    corrected = [e for e in ctx.get("trigger_events", []) if e["kind"] == "fact.corrected"
                 and catalog.is_date_field(e["payload"].get("field", ""))]
    if changed or corrected:
        title = ("Date change moves nothing; window still open" if corrected and not changed
                 else f"Filing window from rules engine: {der.get('earliest_filing')}")
        items.append({"type": "task", "payload": {"kind": "finding", "title": title,
                                                  "title_es": title_es}})
    return items


# ------------------------------------------------------------------------------------------- QA reviewer

def qa_reviewer(ctx: dict, recompute=None) -> list[dict]:
    """Fresh-context audit: recompute from raw facts, challenge weak spots (max 2 rounds), then write the QA memo."""
    lang = ctx.get("language", "en")
    items: list[dict] = []
    fv = _facts(ctx)
    der = ctx.get("derived") or {}
    findings: list[str] = []
    expert: list[str] = []
    # 1. independent recompute
    if recompute is not None and der:
        fresh = recompute()
        keys = ("trip_days", "presence_days", "earliest_filing", "anniversary", "civics_version")
        diffs = [k for k in keys if fresh.get(k) != der.get(k)]
        if diffs:
            items.append({"type": "review_item", "payload": {
                "category": "qa_recompute_mismatch", "note": f"Engine output differs between runs: {diffs}"}})
            findings.append(f"Recompute MISMATCH on {diffs}")
        else:
            bits = [f"{k}={der.get(k)}" for k in ("trip_days", "presence_days") if der.get(k) is not None]
            findings.append("Recompute from raw facts matches" + (f" ({', '.join(bits)})" if bits else ""))
            if bits:
                title_es = "Recalculated the dates of your case" if lang == "en" else "Volvió a calcular las fechas de su caso"
                items.append({"type": "task", "payload": {"kind": "finding",
                                                          "title": "Recompute matches: " + ", ".join(bits),
                                                          "title_es": title_es}})
    # 2. notes on open review items
    for f in _flags(ctx):
        if f["category"] in ("absence_gt_180", "absence_gte_365"):
            items.append({"type": "review_note", "payload": {
                "category": f["category"], "field": f.get("field"),
                "note": "Absence over 180 days — continuous-residence presumption; NEEDS EXPERT CHECK on rebuttal "
                        "standard."}})
            expert.append("continuous residence (absence over 180 days)")
        if f["category"] == "name_mismatch":
            items.append({"type": "review_note", "payload": {
                "category": "name_mismatch", "field": f.get("field"),
                "note": "No fact may use the married name as current legal name without review; every section uses "
                        "the document name. Recommend the reviewer confirm."}})
    # 3. challenges (the Case API caps rounds at 2 per material change)
    # question_es here holds pre-resolved text in ctx["language"] (not necessarily Spanish -- see the
    # case_manager loop above, which stores it back under the matching question_{lang} key).
    challenges: list[dict] = []
    conflict_fields = {f["field"] for f in _flags(ctx, "date_conflict")}
    for k, v in ctx["facts"].items():
        if k in conflict_fields and v.get("hedge") and v["status"] != "confirmed":
            challenges.append({"kind": "challenge", "field": k,
                               "title": f"{k}: hedged and contradicts a document; do not confirm without read-back"})
    if _flags(ctx, "citation") and "background.detail.other_citations" not in fv:
        q = ("Have you received any other fine or citation, anywhere, at any time?" if lang == "en" else
             "¿Ha recibido alguna otra multa o citación, en cualquier lugar y en cualquier momento?")
        challenges.append({"kind": "challenge", "field": "background.detail.other_citations",
                           "title": "Confirm no other citations anywhere, ever", "question_es": q})
    for gap in _employment_gaps(fv):
        key = f"employment.gap.{gap['from']}"
        if key not in fv:
            if lang == "en":
                m1, m2 = MONTHS_EN[gap["from_month"] - 1], MONTHS_EN[gap["to_month"] - 1]
                q = f"Between {m1} and {m2} {gap['year']}, were you out of work or working somewhere else?"
            else:
                m1, m2 = MONTHS_ES[gap["from_month"] - 1], MONTHS_ES[gap["to_month"] - 1]
                q = f"Entre {m1} y {m2} de {gap['year']}, ¿estuvo sin trabajo o trabajó en otro lugar?"
            challenges.append({"kind": "challenge", "field": key,
                               "title": f"Employment gap {gap['from'][:7]}–{gap['to'][:7]} unexplained",
                               "question_es": q})
    ch_rounds = [t for t in ctx["tasks"] if t["agent"] == "qa_reviewer" and t["kind"] == "challenge"]
    open_titles = {t["title"] for t in ch_rounds}
    new = [c for c in challenges if c["title"] not in open_titles]
    for c in new:
        title_es = "Checked the consistency of your answers" if lang == "en" else "Revisó la consistencia de sus respuestas"
        items.append({"type": "task", "payload": {"kind": "challenge", "title": c["title"], "field": c.get("field"),
                                                  "question_es": c.get("question_es"),
                                                  "title_es": title_es}})
    unanswered = [t for t in ch_rounds if t.get("field") and t.get("question_es") and t["field"] not in fv]
    # 4. provenance + edition checks, then the memo (only when nothing new to challenge)
    no_prov = [k for k, v in ctx["facts"].items() if v["status"] == "confirmed" and not v.get("source")]
    findings.append("Every confirmed field has provenance" if not no_prov else f"Missing provenance: {no_prov}")
    expert.append("form edition (04/01/24 vs 01/20/25) — re-verify before filing")
    stops = [f for f in ctx["open_flags"] if f.get("speed") == "stop_now"]
    if not new and (not unanswered or len({t['round'] for t in ch_rounds}) >= 2):
        body = ["**QA memo** (fresh-context audit)", ""] + [f"- {x}" for x in findings]
        if unanswered:
            body.append(f"- Remaining challenges (cap reached): {', '.join(t['title'] for t in unanswered)}")
        if stops:
            body.append(f"- {len(stops)} stop-now item(s) open; the related section is empty and blocked. "
                        "QA does not review stop-now items.")
        body.append(f"- Open review items: {len([r for r in ctx['review_items'] if r.get('status') == 'open'])}")
        body.append("- NEEDS EXPERT CHECK: " + "; ".join(sorted(set(expert))))
        items.append({"type": "memo", "payload": {"kind": "qa", "body_md": "\n".join(body)}})
    return items


def _employment_gaps(fv: dict) -> list[dict]:
    jobs = []
    for k, v in fv.items():
        m = re.match(r"employment\[(\d+)\]\.from$", k)
        if m and v and v != catalog.DEFERRED:
            i = m[1]
            jobs.append((str(v), str(fv.get(f"employment[{i}].to") or "present")))
    jobs.sort()
    gaps = []
    for (f1, t1), (f2, _) in zip(jobs, jobs[1:]):
        if t1 == "present" or len(t1) < 7 or len(f2) < 7:
            continue
        a = date.fromisoformat(t1 if len(t1) == 10 else t1 + "-01")
        b = date.fromisoformat(f2 if len(f2) == 10 else f2 + "-01")
        if (b - a).days > 31:
            m_from = a.month % 12 + 1 if a.day > 25 else a.month
            m_to = (b.month - 2) % 12 + 1 if b.day == 1 else b.month
            gaps.append({"from": a.isoformat(), "to": b.isoformat(), "from_month": m_from, "to_month": m_to,
                         "year": a.year})
    return gaps


AGENTS = {"case_manager": case_manager, "doc_paralegal": doc_paralegal, "docketing_clerk": docketing_clerk,
          "qa_reviewer": qa_reviewer}
