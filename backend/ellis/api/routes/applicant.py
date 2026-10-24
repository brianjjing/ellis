"""Applicant client API (/api/a/*): link-token exchange, facts panel, secure entry, uploads, sign-off, packet."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

from ...config import settings
from ...db import Case, Gap, Packet, session_scope
from ...services import auth, bus, case_service as cs, documents as docsvc, review, signoff, views
from ...services.flags import STOP_NOW
from ..deps import APPLICANT_COOKIE, applicant_case, err

router = APIRouter(prefix="/api/a", tags=["applicant"])


class SessionReq(BaseModel):
    token: str


@router.post("/session")
def exchange(body: SessionReq, request: Request, response: Response) -> dict[str, Any]:
    ip = request.client.host if request.client else "?"
    if auth.rate_limited(f"link:{ip}"):
        raise err(429, "rate_limited", "Demasiados intentos. Espere un minuto.")
    with session_scope() as s:
        link, problem = auth.resolve_link(s, body.token)
        if problem == "expired":
            raise err(410, "link_expired", "Este enlace ya venció. Pídale uno nuevo a su clínica.")
        if link is None:
            raise err(404, "link_invalid", "Este enlace no es válido. Pídale uno nuevo a su clínica.")
        case = s.get(Case, link.case_id)
        cs.emit(s, case, "link.opened", {"link_id": link.id}, "applicant", "applicant")
        cookie = auth.sign({"kind": "applicant", "case_id": case.id, "link_id": link.id})
        response.set_cookie(APPLICANT_COOKIE, cookie, httponly=True, samesite="lax", max_age=12 * 3600)
        return views.applicant_case(s, case)


@router.get("/case")
def get_case(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        return views.applicant_case(s, case)


class SecureReq(BaseModel):
    field: str
    value: Any


@router.post("/secure")
def secure(body: SecureReq, request: Request) -> dict[str, Any]:
    """Typed straight to the Case API, bypassing the voice agent. Models only ever see a token."""
    with session_scope() as s:
        case = applicant_case(request, s)
        try:
            res = cs.secure_entry(s, case, body.field, body.value)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message, e.field) from None
        cs.push(s, case, "secure_entry.saved", {"field": body.field})
        return {"saved": True, "field": body.field, "fact_id": res["fact"]["id"]}


class BiographicsReq(BaseModel):
    values: dict[str, Any]


@router.post("/biographics")
def biographics(body: BiographicsReq, request: Request) -> dict[str, Any]:
    allowed = {"sex", "height", "weight", "eye_color", "hair_color", "ethnicity", "race"}
    with session_scope() as s:
        case = applicant_case(request, s)
        saved = []
        for k, v in body.values.items():
            if k not in allowed or v in (None, ""):
                continue
            try:
                cs.secure_entry(s, case, k, v)
                saved.append(k)
            except cs.CaseError as e:
                raise err(e.status, e.code, e.message, e.field) from None
        cs.push(s, case, "biographics.saved", {"fields": saved})
        return {"saved": saved}


@router.post("/documents")
async def upload(request: Request, document_type: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    with session_scope() as s:
        case = applicant_case(request, s)
        try:
            doc = docsvc.store_upload(s, case, document_type, file.filename or "upload", data)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message, e.field) from None
        doc_id = doc.id
    docsvc.extract_async(doc_id)
    return {"document_id": doc_id, "status": "extracting"}


@router.post("/gaps/{gap_id}/decline")
def decline_gap(gap_id: str, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        g = s.get(Gap, gap_id)
        if g is None or g.case_id != case.id:
            raise err(404, "not_found", "not found")
        g.status = "applicant_declined"
        cs.emit(s, case, "gap.declined", {"gap_id": g.id}, "applicant", "applicant")
        cs.after_fact_change(s, case)
        return {"ok": True}


@router.post("/flags/{flag_id}/not_about_me")
def not_about_me(flag_id: str, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        try:
            review.self_report(s, case, flag_id)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message) from None
        return {"ok": True}


@router.get("/review")
def get_review(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        if case.state not in ("ready", "signed"):
            raise err(409, "not_ready", "Su clínica todavía está revisando su caso.")
        return signoff.review_view(s, case)


class ReopenReq(BaseModel):
    section: str


@router.post("/review/reopen")
def reopen(body: ReopenReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        try:
            signoff.reopen(s, case, body.section)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message) from None
        return {"state": case.state}


class SignReq(BaseModel):
    typed_name: str
    attestation_version: str
    section_confirmations: dict[str, bool] | None = None
    read_aloud: bool = False
    assisted_by: str | None = None


@router.post("/signoff")
def do_signoff(body: SignReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        try:
            return signoff.sign(s, case, body.typed_name, body.attestation_version,
                                request.headers.get("user-agent"), body.section_confirmations, body.read_aloud,
                                body.assisted_by)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message, e.field) from None


def signed_url(packet_id: str, ttl_s: int = 900) -> str:
    exp = int(time.time()) + ttl_s
    sig = hmac.new(settings.session_secret.encode(), f"{packet_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"/files/packet/{packet_id}?exp={exp}&sig={sig}"


def check_signed(packet_id: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    good = hmac.new(settings.session_secret.encode(), f"{packet_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(good, sig)


@router.get("/packet")
def packet(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = applicant_case(request, s)
        ps = s.scalars(select(Packet).where(Packet.case_id == case.id, Packet.status == "current",
                                            Packet.kind != "reviewer_summary").order_by(Packet.ts)).all()
        return {"files": [{"id": p.id, "kind": p.kind, "filename": p.filename, "sha256": p.sha256,
                           "url": signed_url(p.id)} for p in ps]}


@router.post("/professional_draft")
def professional_draft(request: Request) -> dict[str, Any]:
    """F2.08: a draft for the applicant's own professional. Ellis sends nothing to anyone."""
    with session_scope() as s:
        case = applicant_case(request, s)
        p = signoff.professional_draft(s, case)
        return {"id": p.id, "filename": p.filename, "url": signed_url(p.id)}


class RepresentationReq(BaseModel):
    professional_files: bool


@router.post("/representation")
def representation(body: RepresentationReq, request: Request) -> dict[str, Any]:
    """F2.09: 'My professional will file for me' → referred_out / prep_only."""
    with session_scope() as s:
        case = applicant_case(request, s)
        if body.professional_files:
            case.sub_mode = "prep_only"
            cs.set_state(s, case, "referred_out", "applicant reports representation", "applicant", "applicant")
        cs.emit(s, case, "representation.chosen", {"professional_files": body.professional_files},
                "applicant", "applicant")
        return {"state": case.state, "sub_mode": case.sub_mode}


files_router = APIRouter(tags=["files"])


@files_router.get("/files/packet/{packet_id}")
def packet_file(packet_id: str, exp: int, sig: str):
    if not check_signed(packet_id, exp, sig):
        raise err(403, "expired", "link expired")
    with session_scope() as s:
        p = s.get(Packet, packet_id)
        if p is None:
            raise err(404, "not_found", "not found")
        return FileResponse(p.storage_path, media_type="application/pdf", filename=p.filename)


# ---------------------------------------------------------------- live stream

def applicant_safe(msg: dict) -> dict | None:
    """What the applicant's screen may receive. Stop-now items never carry a category."""
    kind = msg["kind"]
    p = msg.get("payload") or {}
    if msg.get("transient"):
        return {"type": kind, "payload": p}
    if kind == "flag.raised" and p.get("speed") == STOP_NOW:
        return {"type": kind, "payload": {"speed": STOP_NOW}}
    if kind.split(".")[0] in ("fact", "flag", "task", "doc", "case", "briefing", "review", "packet", "signoff",
                              "derived", "gap", "consent", "section"):
        return {"type": kind, "payload": {k: v for k, v in p.items() if k in ("field", "status", "version", "to",
                                                                              "from", "document_id", "speed")}}
    return None


@router.websocket("/stream")
async def stream(ws: WebSocket):
    payload = auth.unsign(ws.cookies.get(APPLICANT_COOKIE))
    if not payload or payload.get("kind") != "applicant":
        await ws.close(code=4401)
        return
    case_id = payload["case_id"]
    await ws.accept()
    q = bus.subscribe(lambda m: m.get("case_id") == case_id)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=25)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                continue
            out = applicant_safe(msg)
            if out:
                await ws.send_json(out)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)
