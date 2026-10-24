"""Liaison tools (/tools/*), called by the Line agent (or the in-house voice gateway) in the same turn.

Application logging must not log request bodies of /tools/* (stop-now text never persists).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from ...db import CallSession, Case, now, session_scope
from ...services import case_service as cs
from ...services import catalog
from ...services.flags import STOP_NOW
from ..deps import tool_case

router = APIRouter(prefix="/tools", tags=["liaison tools"])


def active_session(s, case: Case, request: Request | None = None, create: bool = True) -> CallSession | None:
    sid = request.headers.get("x-ellis-session") if request else None
    if sid:
        sess = s.get(CallSession, sid)
        if sess and sess.case_id == case.id and sess.ended_at is None:
            return sess
    sess = s.scalars(select(CallSession).where(CallSession.case_id == case.id, CallSession.ended_at.is_(None))
                     .order_by(CallSession.started_at.desc())).first()
    if sess is None and create:
        sess = start_session(s, case, "line")
    return sess


def start_session(s, case: Case, channel: str) -> CallSession:
    for old in s.scalars(select(CallSession).where(CallSession.case_id == case.id, CallSession.ended_at.is_(None))):
        old.ended_at = now()
    sess = CallSession(clinic_id=case.clinic_id, case_id=case.id, channel=channel, started_at=now(),
                       briefing_version=cs.latest_briefing_version(s, case.id))
    s.add(sess)
    s.flush()
    cs.emit(s, case, "session.started", {"session_id": sess.id, "briefing_version": sess.briefing_version,
                                         "channel": channel}, "liaison", "liaison")
    return sess


class SessionStart(BaseModel):
    channel: str = "line"


@router.post("/session_start")
def session_start(body: SessionStart, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        sess = start_session(s, case, body.channel)
        return {"session_id": sess.id, **call_config(s, case)}


def call_config(s, case: Case) -> dict[str, Any]:
    from ...services.clinic_service import clinic_of
    patient = bool((case.settings or {}).get("patient_mode"))
    locale = case.language or "es-MX"
    lang = "en" if locale.startswith("en") else "es"
    return {"case_state": case.state, "first_name": case.first_name, "clinic_name": clinic_of(s, case).name,
            "consent_given": cs.consent_given(s, case), "patient_mode": patient, "language": lang, "locale": locale,
            "stt": {"language": lang, "turn_profile": "patient" if patient else "default"},
            "tts": {"language": lang, "locale": locale, "speed": 0.85 if patient else 1.0, "add_timestamps": True},
            "silence_thresholds_s": [12, 30, 90] if patient else [8, 20, 60],
            "briefing_version": cs.latest_briefing_version(s, case.id)}


@router.post("/session_end")
def session_end(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request, create=False)
        if sess:
            sess.ended_at = now()
            cs.emit(s, case, "session.ended", {"session_id": sess.id}, "liaison", "liaison")
        return {"ok": True}


@router.post("/get_briefing")
def get_briefing(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        active_session(s, case, request)
        return cs.liaison_briefing(s, case)


class RecordFact(BaseModel):
    field: str
    value: Any = None
    hedge: bool = False
    utterance_id: str | None = None
    utterance_text: str | None = None
    interrupted_at_word: str | None = None
    is_correction: bool = False


@router.post("/record_fact")
def record_fact(body: RecordFact, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request)
        try:
            return cs.record_fact(s, case, body.field, body.value, hedge=body.hedge, utterance_id=body.utterance_id,
                                  utterance_text=body.utterance_text, session_id=sess.id if sess else None,
                                  interrupted_at_word=body.interrupted_at_word, is_correction=body.is_correction)
        except cs.CaseError as e:
            # rules / validation problems are returned in-band so the liaison can say tool_failure or read back
            return {"saved": False, "error": {"code": e.code, "message": e.message, "field": e.field}}


class ReadBack(BaseModel):
    field: str
    read_value: str | None = None
    briefing_version: int | None = None


@router.post("/read_back")
def read_back(body: ReadBack, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        return cs.read_back(s, case, body.field, body.briefing_version, body.read_value)


class FlagReq(BaseModel):
    category: str
    field: str | None = None


@router.post("/flag_for_review")
def flag_for_review(body: FlagReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        return cs.flag_for_review(s, case, body.category, body.field)


class StopReq(BaseModel):
    category: str


@router.post("/stop_script")
def stop_script(body: StopReq, request: Request) -> dict[str, Any]:
    """Passthrough: writes flag + review item only; the client plays the locked stop script."""
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request)
        res = cs.stop_now(s, case, body.category, layer=3, session_id=sess.id if sess else None)
        return {"script_key": "stop", "flag_id": res["flag_id"], "speed": STOP_NOW}


class FieldReq(BaseModel):
    field: str


@router.post("/request_secure_entry")
def request_secure_entry(body: FieldReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        d = catalog.field_def(body.field)
        cs.push(s, case, "open_secure_entry", {"field": body.field, "label": catalog.label_es(body.field),
                                               "type": (d or {}).get("type")})
        return {"ok": True, "script_key": "secure_entry"}


class UploadReq(BaseModel):
    document_type: str


@router.post("/request_upload")
def request_upload(body: UploadReq, request: Request) -> dict[str, Any]:
    from ...services.documents import document_label_es
    with session_scope() as s:
        case = tool_case(request, s)
        cs.push(s, case, "open_upload", {"document_type": body.document_type,
                                         "label": document_label_es(body.document_type)})
        return {"ok": True, "script_key": "upload_request", "document_label": document_label_es(body.document_type)}


@router.post("/request_biographics")
def request_biographics(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        cs.push(s, case, "open_biographics", {})
        return {"ok": True}


class TurnReq(BaseModel):
    text: str


@router.post("/applicant_turn")
def applicant_turn(body: TurnReq, request: Request) -> dict[str, Any]:
    """Handler-only (not an LLM tool): store a final transcript after the in-loop keyword check."""
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request)
        res = cs.applicant_turn(s, case, body.text, sess.id if sess else None)
        res.pop("text", None)
        return res


class SaidReq(BaseModel):
    text: str
    locked: bool = False


@router.post("/liaison_said")
def liaison_said(body: SaidReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request)
        u = cs.liaison_utterance(s, case, body.text, sess.id if sess else None, body.locked)
        return {"utterance_id": u.id}


class ThirdParty(BaseModel):
    present: bool
    relation: str | None = None


@router.post("/third_party")
def third_party(body: ThirdParty, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        case = tool_case(request, s)
        sess = active_session(s, case, request)
        sess.third_party_present = body.present
        sess.third_party_relation = body.relation
        cs.emit(s, case, "session.third_party", {"present": body.present, "relation": body.relation},
                "liaison", "liaison")
        return {"ok": True}
