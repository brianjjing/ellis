"""Uploads, sandboxed extraction, applying extractions as document facts, and name checks."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR
from ..db import Case, Document, Extraction, Fact, Flag, VaultValue, now, session_scope
from ..extraction.schemas import IDENTIFIERS, LABELS_EN, LABELS_ES, SCHEMAS
from . import case_service as cs
from . import catalog, keywords, storage, vault
from .values import ValueError_, equal, normalize

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 5
N400_MAX_PAGES = 30  # the whole form in one PDF
# ponytail: a just-stored file handed to its own extraction in this process, so it isn't downloaded back from
# storage; an entry lives until that extraction pops it (a store whose request then fails leaves one behind)
_fresh: dict[str, bytes] = {}
MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"%PDF", "application/pdf", "pdf"),
]


class UploadError(cs.CaseError):
    pass


def sniff(data: bytes) -> tuple[str, str]:
    for sig, mime, ext in MAGIC:
        if data.startswith(sig):
            return mime, ext
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "image/heic", "heic"
    raise UploadError("unsupported_type", "JPG, PNG, HEIC or PDF only")


def strip_metadata(data: bytes, mime: str, max_pages: int = MAX_PAGES) -> tuple[bytes, str]:
    """Drop EXIF / PDF properties. HEIC is converted to JPEG when pillow-heif is available."""
    if mime in ("image/jpeg", "image/png", "image/heic"):
        from PIL import Image
        if mime == "image/heic":
            try:
                import pillow_heif  # type: ignore
                pillow_heif.register_heif_opener()
            except ImportError:
                raise UploadError("heic_unsupported", "HEIC conversion unavailable; please send a JPG") from None
        img = Image.open(io.BytesIO(data))
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))
        out = io.BytesIO()
        fmt = "PNG" if mime == "image/png" else "JPEG"
        if fmt == "JPEG" and clean.mode not in ("RGB", "L"):
            clean = clean.convert("RGB")
        clean.save(out, format=fmt, quality=92)
        return out.getvalue(), ("image/png" if fmt == "PNG" else "image/jpeg")
    if mime == "application/pdf":
        from pypdf import PdfReader, PdfWriter
        r = PdfReader(io.BytesIO(data))
        if len(r.pages) > max_pages:
            raise UploadError("too_many_pages", f"at most {max_pages} pages per file")
        w = PdfWriter()
        for p in r.pages:
            w.add_page(p)
        out = io.BytesIO()
        w.write(out)
        return out.getvalue(), mime
    return data, mime  # pragma: no cover


def store_upload(s: Session, case: Case, document_type: str, filename: str, data: bytes,
                 uploaded_by: str = "applicant", actor_type: str = "applicant") -> Document:
    if document_type not in SCHEMAS:
        raise UploadError("unknown_document_type", f"unknown document type {document_type}")
    if len(data) > MAX_BYTES:
        raise UploadError("too_large", "10 MB per file at most")
    mime, ext = sniff(data)
    orig_sha = hashlib.sha256(data).hexdigest()
    clean, mime = strip_metadata(data, mime, N400_MAX_PAGES if document_type == "n400" else MAX_PAGES)
    ext = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}[mime]
    doc = Document(clinic_id=case.clinic_id, case_id=case.id, document_type=document_type,
                   filename=os.path.basename(filename or f"upload.{ext}")[:200], mime=mime, storage_path="",
                   sha256=orig_sha, size=len(clean), status="extracting", uploaded_by=uploaded_by, ts=now())
    s.add(doc)
    s.flush()
    doc.storage_path = f"{case.id}/{doc.id}.{ext}"
    storage.put(doc.storage_path, clean, mime)
    _fresh[doc.id] = clean
    cs.emit(s, case, "doc.uploaded", {"document_id": doc.id, "document_type": document_type}, actor_type, uploaded_by)
    cs.push(s, case, "document.status", {"document_id": doc.id, "status": "extracting",
                                         "document_type": document_type})
    return doc


def run_extraction_subprocess(doc: Document, on_field: Callable[[dict], None] | None = None) -> dict[str, Any]:
    """Sandbox: separate process, no DB or storage credentials, 60 s timeout. (Container hardening is deploy config.)

    The parent fetches the file and hands the worker a local path. The last line is the result; any line before it
    is a field an n400 sweep has just passed, handed to on_field as it arrives.
    """
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "ANTHROPIC_API_KEY",
                                                         "ELLIS_EXTRACTION_MODEL", "SSL_CERT_FILE",
                                                         "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
                                                         "REQUESTS_CA_BUNDLE")}
    try:
        with storage.local_file(doc.storage_path, _fresh.pop(doc.id, None)) as path:
            proc = subprocess.Popen(
                # -E -s, not -I: -I also drops the cwd from sys.path, and then `ellis` only imports when it is
                # pip-installed in a way isolated mode still sees (true of uv's backend/.venv, not the repo .venv)
                [sys.executable, "-E", "-s", "-m", "ellis.extraction.worker", doc.document_type, path, doc.mime,
                 doc.sha256],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(BACKEND_DIR))
            timer = threading.Timer(60, proc.kill)
            timer.start()
            last = None
            try:
                for line in proc.stdout:
                    msg = json.loads(line)
                    if "field" in msg and on_field is not None:
                        on_field(msg)
                    else:
                        last = msg
                err = proc.stderr.read()
                proc.wait()
            finally:
                timer.cancel()
        if proc.returncode == -9:
            return {"ok": False, "error": "timeout"}
        return last or {"ok": False, "error": err[-500:] or "no output"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def extract_async(doc_id: str) -> None:
    def work():
        with session_scope() as s:
            doc = s.get(Document, doc_id)
            snapshot = Document(id=doc.id, document_type=doc.document_type, storage_path=doc.storage_path,
                                mime=doc.mime, sha256=doc.sha256)
        if snapshot.document_type == "n400":
            return fill_n400(doc_id)
        result = run_extraction_subprocess(snapshot)
        with session_scope() as s:
            doc = s.get(Document, doc_id)
            case = s.get(Case, doc.case_id)
            apply_extraction(s, case, doc, result)
    if os.environ.get("ELLIS_EXTRACTION_SYNC") == "1":
        work()
    else:
        threading.Thread(target=work, daemon=True).start()


def _iso(v: Any) -> str | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def apply_extraction(s: Session, case: Case, doc: Document, result: dict[str, Any]) -> None:
    if not result.get("ok"):
        doc.status = "failed"
        doc.checks = {**(doc.checks or {}), "error": result.get("error")}
        cs.emit(s, case, "doc.extraction_failed", {"document_id": doc.id, "error": str(result.get("error"))[:200]},
                "system", "extraction_worker")
        cs.push(s, case, "document.status", {"document_id": doc.id, "status": "failed",
                                             "document_type": doc.document_type})
        cs.after_fact_change(s, case)
        return
    data = dict(result["data"])
    # identifiers into the vault before anything else sees the extraction
    vaulted = {}
    for k, token in IDENTIFIERS.items():
        if data.get(k):
            vaulted[k] = str(data[k])
            data[k] = token
    quality = data.get("quality", "low")
    x = Extraction(clinic_id=case.clinic_id, case_id=case.id, document_id=doc.id, data=data, quality=quality,
                   quality_reasons=data.get("quality_reasons", []), extractor=result.get("extractor", "?"), ts=now())
    s.add(x)
    doc.quality = quality
    doc.status = "extracted"
    s.flush()
    applied = []
    owner_ok = True
    if quality != "low":
        owner_ok = _belongs_to_applicant(s, case, doc, data)
        if owner_ok:
            applied = _apply_fields(s, case, doc, data, vaulted, quality)
    doc.checks = {**(doc.checks or {}), "legible": quality != "low", "belongs_to_applicant": owner_ok,
                  "applied_fields": applied}
    cs.emit(s, case, "doc.extracted", {"document_id": doc.id, "document_type": doc.document_type,
                                       "quality": quality, "applied_fields": applied}, "system", "extraction_worker")
    cs.push(s, case, "document.status", {"document_id": doc.id, "status": "extracted", "quality": quality,
                                         "document_type": doc.document_type})
    if applied:
        check_names(s, case)
        cs.evaluate_rules(s, case)
        # a stamp can resolve or create trip date conflicts
    if doc.document_type == "passport":
        _recheck_trip_conflicts(s, case)
    cs.after_fact_change(s, case)


def _belongs_to_applicant(s: Session, case: Case, doc: Document, data: dict) -> bool:
    """Wrong person's document: given names don't overlap at all → flag, apply nothing."""
    given = data.get("given_name")
    if doc.document_type == "marriage_certificate":
        names = " ".join(filter(None, [data.get("spouse_1_name"), data.get("spouse_2_name")]))
        given = names
    elif doc.document_type in ("lease",):
        given = " ".join(data.get("tenant_names") or [])
    elif doc.document_type in ("tax_transcript",):
        given = data.get("taxpayer_name")
    elif doc.document_type in ("benefit_letter",):
        given = data.get("beneficiary_name")
    elif doc.document_type == "n400":
        given = (data.get("answers") or {}).get("name.given")
    if not given:
        return True
    view = cs.cur_view(s, case.id)
    known = keywords.name_tokens(case.first_name)
    gv = view.get("name.given", {}).get("value")
    if gv and gv != catalog.DEFERRED:
        known |= keywords.name_tokens(str(gv))
    if known & keywords.name_tokens(given):
        return True
    cs.raise_flag(s, case, "document_owner", layer=2, field=None,
                  detail={"document_id": doc.id, "reason": "document may belong to someone else"})
    return False


def _apply_fields(s: Session, case: Case, doc: Document, data: dict, vaulted: dict, quality: str) -> list[str]:
    t = doc.document_type
    m: dict[str, Any] = {}
    if t == "green_card":
        m = {"lpr_since": _iso(data.get("resident_since")), "dob": _iso(data.get("dob")),
             "country_of_birth": data.get("country_of_birth"),
             "name.on_green_card": " ".join(filter(None, [data.get("given_name"), data.get("family_name")])) or None,
             "name.given": _title(data.get("given_name")), "name.family": _title(data.get("family_name"))}
        if vaulted.get("a_number"):
            m["a_number"] = vaulted["a_number"]
    elif t == "passport":
        m = {"nationality": data.get("nationality"), "dob": _iso(data.get("dob"))}
        if vaulted.get("passport_number"):
            m["passport_number"] = vaulted["passport_number"]
    elif t == "marriage_certificate":
        view = cs.cur_view(s, case.id)
        mine = keywords.name_tokens(case.first_name)
        spouse = None
        for nm in (data.get("spouse_1_name"), data.get("spouse_2_name")):
            if nm and not (keywords.name_tokens(nm) & mine):
                spouse = nm
        m = {"spouse.name": _title(spouse), "spouse.marriage_date": _iso(data.get("marriage_date"))}
        if view.get("marital.status") is None:
            pass
    applied = []
    for field, value in m.items():
        if value in (None, ""):
            continue
        if _apply_doc_fact(s, case, doc, field, value, quality):
            applied.append(field)
    return applied


def schema_problem() -> str | None:
    """Checked before an N-400 fills anything: every table and column the models expect exists in the live database.
    One query for the whole schema, not one per table: on a hosted database every round trip shows."""
    from sqlalchemy import text
    from ..db import Base, engine
    with engine().connect() as con:
        q = ("select table_name, column_name from information_schema.columns where table_schema = current_schema()"
             if con.dialect.name == "postgresql" else
             "select m.name, p.name from sqlite_master m join pragma_table_info(m.name) p where m.type = 'table'")
        live: dict[str, set[str]] = {}
        for table, column in con.execute(text(q)):
            live.setdefault(table, set()).add(column)
    for table in Base.metadata.sorted_tables:
        if table.name not in live:
            return f"table {table.name} is missing"
        if missing := [c.name for c in table.columns if c.name not in live[table.name]]:
            return f"{table.name} is missing {', '.join(missing)}"
    return None


def fill_n400(doc_id: str) -> None:
    """An uploaded N-400 fills the form in one sweep: the worker reads the file once and streams each app field as it
    passes it; each is written (or cleared) as it arrives and each part is committed as the sweep leaves it, so the
    parts view fills part by part. The case's answers are read once up front, not once per field."""
    with session_scope() as s:
        doc = s.get(Document, doc_id)
        case = s.get(Case, doc.case_id)
        problem = schema_problem()
        if problem:
            return apply_extraction(s, case, doc, {"ok": False, "error": f"database check failed: {problem}"})
        answers: dict[str, Any] = {}
        applied: list[str] = []
        state = {"section": None, "owner_ok": True}
        facts: dict[str, list[Fact]] | None = None  # None: no consent yet, values wait in the prefill bag
        if cs.consent_given(s, case):
            facts = {}
            for f in cs.facts_for(s, case.id):
                facts.setdefault(f.field, []).append(f)

        def on_field(m: dict) -> None:
            field, value = m["field"], m["value"]
            if m["section"] != state["section"]:
                state["section"] = m["section"]
                cs.push(s, case, "n400.fill", {"document_id": doc.id, "section": m["section"]})
                s.commit()  # the finished part's answers and the spinner's move reach the screen together
            if field == "name.given" and value:  # fills either way; someone else's name is flagged for the clinic
                state["owner_ok"] = _belongs_to_applicant(s, case, doc, {"answers": {field: value}})
            if _set_n400_field(s, case, doc, field, value, facts):
                applied.append(field)
            answers[field] = catalog.mask_token(field) if value and catalog.is_masked(field) else value

        result = run_extraction_subprocess(doc, on_field)
        if not result.get("ok"):
            s.rollback()
            cs.push(s, case, "n400.fill", {"document_id": doc.id, "section": None})
            return apply_extraction(s, case, doc, result)
        s.add(Extraction(clinic_id=case.clinic_id, case_id=case.id, document_id=doc.id, quality="high",
                         data={"quality": "high", "quality_reasons": [], "answers": answers},
                         extractor=result["extractor"], ts=now()))
        doc.quality, doc.status = "high", "extracted"
        doc.checks = {**(doc.checks or {}), "legible": True, "belongs_to_applicant": state["owner_ok"],
                      "applied_fields": applied}
        cs.emit(s, case, "doc.extracted", {"document_id": doc.id, "document_type": "n400", "quality": "high",
                                           "applied_fields": applied}, "system", "extraction_worker")
        cs.push(s, case, "n400.fill", {"document_id": doc.id, "section": None})
        cs.push(s, case, "document.status", {"document_id": doc.id, "status": "extracted", "quality": "high",
                                             "document_type": "n400"})
        check_names(s, case)
        cs.evaluate_rules(s, case)
        cs.after_fact_change(s, case)


def _coerce(field: str, value: Any) -> Any:
    """The N-400's spellings into the catalog's: mm/dd/yyyy, "$72,000", "biological daughter"."""
    d = catalog.field_def(field) or {}
    if not isinstance(value, str):
        return value
    if catalog.is_date_field(field) and (m := re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value)):
        return f"{m[3]}-{m[1]}-{m[2]}"
    if d.get("type") == "int":
        return re.sub(r"\D", "", value) or value
    if d.get("type") == "bool":  # a yes/no the form implies, e.g. trips.any from a filled trip row
        return keywords.fold(value) not in ("n", "no")
    if d.get("type") == "enum":
        folded = keywords.fold(value).replace(" ", "_")
        return next((o for o in d.get("options", []) if o in folded), value)
    return value


def _set_n400_field(s: Session, case: Case, doc: Document, field: str, value: Any,
                    facts: dict[str, list[Fact]] | None) -> bool:
    """The upload overrides the online form: its value replaces the answer; a blank or unreadable one clears it.
    facts is the case's live answers by field (kept current here), or None before consent."""
    if facts is None:  # no fact rows before consent: the value waits in the prefill bag
        if value in (None, "", []):
            return False
        from .accounts import stash_extracted
        stash_extracted(s, case, field, value, document_id=doc.id)
        return True
    others = facts.get(field, [])
    cur = ([f for f in others if f.status != "disputed"] or others or [None])[-1]  # as cs.current_facts picks
    if cur is not None and cur.value == catalog.DEFERRED:
        return False  # deferred to a licensed professional: not the upload's to undo
    try:
        value = None if value in (None, "", []) else normalize(field, _coerce(field, value))
    except ValueError_:
        value = None  # can't tell what the form says: fill it with nothing
    if value is None:
        if others:
            cs._supersede(others, None, "cleared by N-400 upload")
            cs.emit(s, case, "fact.cleared", {"field": field, "document_id": doc.id}, "system", "extraction_worker")
            facts[field] = []
        return False
    masked = catalog.is_masked(field)
    if cur is not None and cur.status == "confirmed" and not masked and equal(field, cur.value, value):
        return True  # unchanged (a masked value is rewritten rather than read back out of the vault)
    f = cs._insert_fact(s, case, field, catalog.mask_token(field) if masked else value, "confirmed", "document",
                        provenance={"document_id": doc.id, "document_type": "n400"}, proposed_by="extraction",
                        supersedes=cur.id if cur else None, confidence="high")
    cs._supersede(others, f, "replaced by N-400 upload")
    facts[field] = [f]
    if masked:
        s.add(VaultValue(fact_id=f.id, clinic_id=case.clinic_id, case_id=case.id, field=field,
                         ciphertext=vault.encrypt(str(value)), last4=str(value)[-4:]))
    cs.emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "source": "document", "status": "confirmed",
                                       "masked": masked}, "system", "extraction_worker")
    cs._mark_material(case, field)
    cs._layer1(s, case, field, value, None)  # a "yes" on a background question raises its flag, as when spoken
    return True


def _title(v: Any) -> str | None:
    if not v:
        return None
    return " ".join(w.capitalize() for w in str(v).split())


def _apply_doc_fact(s: Session, case: Case, doc: Document, field: str, value: Any, quality: str) -> bool:
    if catalog.field_def(field) is None:
        return False
    if not cs.consent_given(s, case):
        # Same bag as the guest prefill. record_fact applies it once consent exists. No fact row before that.
        from .accounts import stash_extracted
        stash_extracted(s, case, field, value, document_id=doc.id)
        return True
    existing = cs.facts_for(s, case.id, field)
    cur = cs.current_facts(s, case.id).get(field)
    if cur is not None and cur.value == catalog.DEFERRED:
        return False
    masked = catalog.is_masked(field)
    stored = catalog.mask_token(field) if masked else value
    prov = {"document_id": doc.id, "document_type": doc.document_type}
    if masked:
        if cur is not None and cur.source == "applicant_typed":
            same = cs.vault_lookup(s, cur.id) == str(value)
            if not same and quality == "high":
                cs.raise_flag(s, case, "document_conflict", layer=2, field=field,
                              detail={"document_id": doc.id, "reason": "typed value differs from document"})
            return False
        f = cs._insert_fact(s, case, field, stored, "confirmed" if quality == "high" else "proposed", "document",
                            provenance=prov, proposed_by="extraction", supersedes=cur.id if cur else None,
                            confidence=quality)
        cs._supersede(existing, f)
        s.add(VaultValue(fact_id=f.id, clinic_id=case.clinic_id, case_id=case.id, field=field,
                         ciphertext=vault.encrypt(str(value)), last4=str(value)[-4:]))
        cs.emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "source": "document", "masked": True},
                "system", "extraction_worker")
        return True
    if cur is not None and cur.source == "document":
        if equal(field, cur.value, value):
            return False
        other_doc = cur.provenance.get("document_id")
        if quality == "high" and cs._doc_quality(s, other_doc) == "high" and other_doc != doc.id:
            # two documents disagree: neither wins
            cur.status = "disputed"
            f = cs._insert_fact(s, case, field, value, "disputed", "document", provenance=prov,
                                proposed_by="extraction", confidence=quality, note=f"conflicts with {other_doc}")
            cs.raise_flag(s, case, "document_conflict", layer=2, field=field,
                          detail={"documents": [other_doc, doc.id]})
            cs.emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "source": "document",
                                               "status": "disputed"}, "system", "extraction_worker")
            return True
    if cur is not None and cur.source != "document":
        if equal(field, cur.value, value):
            if quality == "high" and cur.status != "confirmed":
                cur.status = "confirmed"
                cur.confirmed_at = now()
                cur.matches_document = doc.id
                cs.emit(s, case, "fact.confirmed", {"field": field, "fact_id": cur.id, "via": "document_match"},
                        "system", "extraction_worker")
                for fl in cs._open_flags(s, case, "date_conflict", field):
                    cs.resolve_flag(s, case, fl, "matches document")
            else:
                cur.matches_document = doc.id
            return True
        if quality != "high":
            return False  # a low/medium document never outranks the applicant
        if cur.status == "confirmed" and catalog.is_material(field) and not field.startswith("name"):
            # the applicant already confirmed something else: disputed, blocking review item
            cs.raise_flag(s, case, "document_conflict", layer=2, field=field,
                          detail={"document_id": doc.id, "reason": "confirmed answer differs from document"})
        cur.status = "disputed"
        cur.note = (cur.note + "; " if cur.note else "") + f"conflicts with document {doc.id}"
        f = cs._insert_fact(s, case, field, value, "proposed", "document", provenance=prov, proposed_by="extraction",
                            confidence=quality, note="document outranks recall; read back to confirm")
        cs.emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "source": "document",
                                           "status": "proposed", "conflict_with": cur.id}, "system",
                "extraction_worker")
        if catalog.is_date_field(field):
            cs.raise_flag(s, case, "date_conflict", layer=2, field=field, detail={"documents": [doc.id]})
        cs._mark_material(case, field)
        return True
    doc_only = (catalog.field_def(field) or {}).get("capture") == "D"
    status = "confirmed" if doc_only and quality == "high" else "proposed"
    f = cs._insert_fact(s, case, field, value, status, "document", provenance=prov, proposed_by="extraction",
                        confidence=quality)
    cs.emit(s, case, "fact.recorded", {"field": field, "fact_id": f.id, "source": "document", "status": status},
            "system", "extraction_worker")
    return True


def _recheck_trip_conflicts(s: Session, case: Case) -> None:
    view = cs.cur_view(s, case.id)
    for k, v in view.items():
        m = catalog.LIST_RE.match(k)
        if not (m and m["list"] == "trips" and m["sub"] in ("departure", "return")):
            continue
        match, conflicts = cs._doc_check(s, case.id, k, v["value"])
        f = s.get(Fact, v["id"])
        if match and f.status != "confirmed" and not f.hedge:
            f.status = "confirmed"
            f.matches_document = match
        elif conflicts and f.status != "confirmed":
            cs.raise_flag(s, case, "date_conflict", layer=2, field=k,
                          detail={"documents": sorted({c["document_id"] for c in conflicts})})


def check_names(s: Session, case: Case) -> list[Flag | None]:
    """name_mismatch (layer 2): document name vs names the applicant gave, compared in code."""
    view = cs.cur_view(s, case.id)
    doc_given = doc_family = None
    for x in s.scalars(select(Extraction).where(Extraction.case_id == case.id, Extraction.quality == "high")):
        if x.data.get("given_name") and x.data.get("family_name"):
            doc_given, doc_family = x.data["given_name"], x.data["family_name"]
            break
    if not doc_given:
        return []
    spoken: list[tuple[str, str]] = []
    g = view.get("name.given")
    fam = view.get("name.family")
    if g and fam and g["source"] == "spoken" and fam["source"] == "spoken":
        spoken.append((str(g["value"]), str(fam["value"])))
    used = view.get("names.used", {}).get("value") or []
    if isinstance(used, list):
        for nm in used:
            parts = str(nm).split()
            if len(parts) >= 2:
                gtoks = keywords.name_tokens(doc_given)
                given_part = [p for p in parts if keywords.fold(p) in gtoks]
                fam_part = [p for p in parts if keywords.fold(p) not in gtoks]
                spoken.append((" ".join(given_part) or parts[0], " ".join(fam_part)))
    out = []
    for sg, sf in spoken:
        res = keywords.names_match(sg, sf, doc_given, doc_family)
        if not res["family"] or not res["given"]:
            out.append(cs.raise_flag(s, case, "name_mismatch", layer=2, field="name.family",
                                     detail={"given_match": res["given"], "family_match": res["family"]}))
            break
    return out


def document_label_es(doc_type: str) -> str:
    return LABELS_ES.get(doc_type, "documento")


def document_label(doc_type: str, lang: str = "es") -> str:
    return LABELS_EN.get(doc_type, "document") if lang == "en" else document_label_es(doc_type)
