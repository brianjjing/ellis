"""Uploads, sandboxed extraction, applying extractions as document facts, and name checks."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import BACKEND_DIR
from ..db import Case, Document, Extraction, Fact, Flag, VaultValue, now, session_scope
from ..extraction.schemas import IDENTIFIERS, LABELS_EN, LABELS_ES, SCHEMAS
from . import case_service as cs
from . import catalog, keywords, storage, vault
from .values import equal

MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 5
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


def strip_metadata(data: bytes, mime: str) -> tuple[bytes, str]:
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
        if len(r.pages) > MAX_PAGES:
            raise UploadError("too_many_pages", f"at most {MAX_PAGES} pages per file")
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
    clean, mime = strip_metadata(data, mime)
    ext = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}[mime]
    doc = Document(clinic_id=case.clinic_id, case_id=case.id, document_type=document_type,
                   filename=os.path.basename(filename or f"upload.{ext}")[:200], mime=mime, storage_path="",
                   sha256=orig_sha, size=len(clean), status="extracting", uploaded_by=uploaded_by, ts=now())
    s.add(doc)
    s.flush()
    doc.storage_path = f"{case.id}/{doc.id}.{ext}"
    storage.put(doc.storage_path, clean, mime)
    cs.emit(s, case, "doc.uploaded", {"document_id": doc.id, "document_type": document_type}, actor_type, uploaded_by)
    cs.push(s, case, "document.status", {"document_id": doc.id, "status": "extracting",
                                         "document_type": document_type})
    return doc


def run_extraction_subprocess(doc: Document) -> dict[str, Any]:
    """Sandbox: separate process, no DB or storage credentials, 60 s timeout. (Container hardening is deploy config.)

    The parent fetches the file and hands the worker a local path.
    """
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "ANTHROPIC_API_KEY",
                                                         "ELLIS_EXTRACTION_MODEL", "SSL_CERT_FILE",
                                                         "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
                                                         "REQUESTS_CA_BUNDLE")}
    env["PYTHONPATH"] = str(BACKEND_DIR)
    try:
        with storage.local_file(doc.storage_path) as path:
            proc = subprocess.run(
                [sys.executable, "-I", "-m", "ellis.extraction.worker", doc.document_type, path, doc.mime,
                 doc.sha256],
                capture_output=True, text=True, timeout=60, env=env, cwd=str(BACKEND_DIR))
        out = proc.stdout.strip().splitlines()
        return json.loads(out[-1]) if out else {"ok": False, "error": proc.stderr[-500:] or "no output"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def extract_async(doc_id: str) -> None:
    def work():
        with session_scope() as s:
            doc = s.get(Document, doc_id)
            snapshot = Document(id=doc.id, document_type=doc.document_type, storage_path=doc.storage_path,
                                mime=doc.mime, sha256=doc.sha256)
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


def _title(v: Any) -> str | None:
    if not v:
        return None
    return " ".join(w.capitalize() for w in str(v).split())


def _apply_doc_fact(s: Session, case: Case, doc: Document, field: str, value: Any, quality: str) -> bool:
    if catalog.field_def(field) is None:
        return False
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
