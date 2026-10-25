"""Clinic workspace API (/api/clinic/*): cookie auth, role-checked, every query scoped by clinic_id."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select

from ...config import settings
from ...db import Case, Clinic, Document, Event, Memo, ReviewItem, StaffUser, now, session_scope
from ...services import auth, bus, case_service as cs, catalog, documents as docsvc, languages, review, storage, views
from ...services.demo import simulate_answers
from ...services.flags import STOP_NOW
from ..deps import APPLICANT_COOKIE, STAFF_COOKIE, clinic_case, err, staff_user

router = APIRouter(prefix="/api/clinic", tags=["clinic"])
ALL = ("intake", "reviewer", "admin")


class LoginReq(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginReq, request: Request, response: Response) -> dict[str, Any]:
    ip = request.client.host if request.client else "?"
    if auth.rate_limited(f"login:{ip}", limit=20):
        raise err(429, "rate_limited", "too many attempts")
    with session_scope() as s:
        u = s.scalars(select(StaffUser).where(StaffUser.email == body.email.strip().lower())).first()
        if u is None or not u.active or not auth.verify_password(u.password_hash, body.password):
            raise err(401, "bad_credentials", "wrong email or password")
        response.set_cookie(STAFF_COOKIE, auth.sign({"kind": "staff", "staff_id": u.id}), httponly=True,
                            samesite="lax", max_age=12 * 3600)
        response.delete_cookie(APPLICANT_COOKIE)  # one role per browser, as /api/auth/login does
        cs.emit(s, None, "staff.login", {"staff_id": u.id}, "staff", u.id, clinic_id=u.clinic_id)
        return me_payload(s, u)


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(STAFF_COOKIE)
    response.delete_cookie(APPLICANT_COOKIE)
    return {"ok": True}


def me_payload(s, u: StaffUser) -> dict[str, Any]:
    c = s.get(Clinic, u.clinic_id)
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "clinic": {"id": c.id, "name": c.name, "is_demo": c.is_demo, "settings": c.settings}}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        return me_payload(s, staff_user(request, s))


@router.get("/cases")
def list_cases(request: Request, stage: str | None = None, stop_now: bool = False, mine: bool = False,
               inactive: bool = False) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        q = select(Case).where(Case.clinic_id == u.clinic_id).order_by(Case.last_event_at.desc())
        rows = []
        for c in s.scalars(q):
            if stage and c.state != stage:
                continue
            if mine and c.assigned_reviewer != u.id:
                continue
            if inactive and c.last_event_at and (now() - cs._aware(c.last_event_at)) < timedelta(days=7):
                continue
            r = views.case_row(s, c)
            if stop_now and not r["has_stop_now"]:
                continue
            rows.append(r)
        reviewers = [{"id": x.id, "name": x.name} for x in s.scalars(
            select(StaffUser).where(StaffUser.clinic_id == u.clinic_id, StaffUser.role.in_(["reviewer", "admin"]),
                                    StaffUser.active.is_(True)))]
        return {"cases": rows, "reviewers": reviewers}


class NewCase(BaseModel):
    first_name: str
    last_name: str
    phone: str | None = None
    language: str = "en-US"
    patient_mode: bool = False
    assigned_reviewer: str | None = None


@router.post("/cases")
def create_case(body: NewCase, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        if not languages.supported(body.language):
            raise err(400, "language", "unsupported language")
        body.language = languages.normalize(body.language)
        if body.assigned_reviewer:
            r = s.get(StaffUser, body.assigned_reviewer)
            if r is None or r.clinic_id != u.clinic_id:
                raise err(400, "bad_reviewer", "unknown reviewer")
        c = Case(clinic_id=u.clinic_id, first_name=body.first_name.strip(), last_name=body.last_name.strip(),
                 phone=body.phone, language=body.language, settings={"patient_mode": body.patient_mode},
                 assigned_reviewer=body.assigned_reviewer, created_by=u.id, created_at=now())
        s.add(c)
        s.flush()
        cs.emit(s, c, "case.created", {"by": u.id}, "staff", u.id)
        token = auth.issue_link(s, c)
        cs.emit(s, c, "link.issued", {"by": u.id}, "staff", u.id)
        cs.publish_briefing(s, c, {"queue": []}, proposed_by="case_api")
        return {"case": views.case_row(s, c), "link": f"{settings.public_base_url}/a/{token}"}


@router.post("/cases/{case_id}/link")
def new_link(case_id: str, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        token = auth.issue_link(s, c)
        cs.emit(s, c, "link.issued", {"by": u.id, "revoked_previous": True}, "staff", u.id)
        return {"link": f"{settings.public_base_url}/a/{token}"}


@router.get("/cases/{case_id}")
def case_detail(case_id: str, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        return views.clinic_case_detail(s, c, u)


class RevealReq(BaseModel):
    field: str
    fact_id: str | None = None


@router.post("/cases/{case_id}/reveal")
def reveal(case_id: str, body: RevealReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("reviewer", "admin"))
        c = clinic_case(s, u, case_id)
        f = cs.current_facts(s, c.id).get(body.field)
        if f is None or not catalog.is_masked(body.field):
            raise err(404, "not_found", "no masked value")
        value = cs.vault_lookup(s, f.id)
        cs.emit(s, c, "vault.revealed", {"field": body.field, "fact_id": f.id}, "staff", u.id)
        return {"field": body.field, "value": value}


@router.get("/review")
def review_queue(request: Request, all_cases: bool = False) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("reviewer", "admin"))
        q = (select(ReviewItem, Case).join(Case, Case.id == ReviewItem.case_id)
             .where(Case.clinic_id == u.clinic_id, ReviewItem.status.in_(["open", "case_blocked"])))
        if not all_cases and u.role == "reviewer":
            q = q.where(Case.assigned_reviewer == u.id)
        items = [views.review_item_view(s, r, u) for r, _ in s.execute(q.order_by(ReviewItem.ts))]
        items.sort(key=lambda i: (i["speed"] != STOP_NOW, i["ts"]))  # stop-now pinned at top, then oldest first
        cases = {}
        for i in items:
            if i["case_id"] not in cases:
                c = s.get(Case, i["case_id"])
                cases[i["case_id"]] = {"gate": cs.gate_status(s, c), "state": c.state, "applicant": c.display_name}
        return {"items": items, "cases": cases}


class DecisionReq(BaseModel):
    decision: str
    note: str


@router.post("/review/{item_id}/decision")
def decision(item_id: str, body: DecisionReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("reviewer", "admin"))
        item = s.get(ReviewItem, item_id)
        if item is None:
            raise err(404, "not_found", "not found")
        clinic_case(s, u, item.case_id)
        try:
            return review.decide(s, item, body.decision, body.note, u)
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message, e.field) from None


@router.post("/cases/{case_id}/ready")
def ready(case_id: str, request: Request) -> Any:
    with session_scope() as s:
        u = staff_user(request, s, ("reviewer", "admin"))
        c = clinic_case(s, u, case_id)
        try:
            return review.mark_ready(s, c, u)
        except cs.CaseError as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=e.status, content={"error": {
                "code": e.code, "message": e.message, "failing": getattr(e, "details", [])}})


class PatchCase(BaseModel):
    assigned_reviewer: str | None = None
    patient_mode: bool | None = None
    close: bool | None = None
    referred_out: bool | None = None


@router.patch("/cases/{case_id}")
def patch_case(case_id: str, body: PatchCase, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        if body.assigned_reviewer is not None:
            r = s.get(StaffUser, body.assigned_reviewer)
            if r is None or r.clinic_id != u.clinic_id:
                raise err(400, "bad_reviewer", "unknown reviewer")
            c.assigned_reviewer = r.id
            cs.emit(s, c, "case.reassigned", {"reviewer": r.id}, "staff", u.id)
        if body.patient_mode is not None:
            c.settings = {**(c.settings or {}), "patient_mode": body.patient_mode}
            cs.emit(s, c, "case.settings_changed", {"patient_mode": body.patient_mode}, "staff", u.id)
        if body.referred_out:
            cs.set_state(s, c, "referred_out", "clinic does not handle this issue", "staff", u.id)
        if body.close:
            cs.set_state(s, c, "closed", "clinic closed the case", "staff", u.id)
        return views.case_row(s, c)


class NoteReq(BaseModel):
    body: str


@router.post("/cases/{case_id}/notes")
def add_note(case_id: str, body: NoteReq, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        m = Memo(clinic_id=c.clinic_id, case_id=c.id, kind="note", body_md=body.body, proposed_by=f"staff:{u.id}",
                 ts=now())
        s.add(m)
        s.flush()
        cs.emit(s, c, "note.added", {"memo_id": m.id}, "staff", u.id)
        return {"id": m.id}


class StaffSecure(BaseModel):
    field: str
    value: Any


@router.post("/cases/{case_id}/secure")
def staff_secure(case_id: str, body: StaffSecure, request: Request) -> dict[str, Any]:
    """Intake staff may type a sensitive number on the applicant's behalf (logged)."""
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        try:
            cs.secure_entry(s, c, body.field, body.value, actor=u.id, actor_type="staff")
        except cs.CaseError as e:
            raise err(e.status, e.code, e.message, e.field) from None
        return {"saved": True}


@router.post("/cases/{case_id}/documents")
async def staff_upload(case_id: str, request: Request, document_type: str = Form(...),
                       file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()

    def store() -> str:  # database + storage round trips: off the event loop
        with session_scope() as s:
            u = staff_user(request, s, ALL)
            c = clinic_case(s, u, case_id)
            try:
                return docsvc.store_upload(s, c, document_type, file.filename or "upload", data, uploaded_by=u.id,
                                           actor_type="staff").id
            except cs.CaseError as e:
                raise err(e.status, e.code, e.message) from None
    doc_id = await asyncio.to_thread(store)
    docsvc.extract_async(doc_id)
    return {"document_id": doc_id, "status": "extracting"}


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: str, request: Request):
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        d = s.get(Document, doc_id)
        if d is None:
            raise err(404, "not_found", "not found")
        clinic_case(s, u, d.case_id)
        key, mime = d.storage_path, d.mime
    return Response(storage.get(key), media_type=mime)


@router.get("/cases/{case_id}/packet/{packet_id}")
def case_packet(case_id: str, packet_id: str, request: Request) -> dict[str, Any]:
    from ...db import Packet
    from .applicant import signed_url
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        p = s.get(Packet, packet_id)
        if p is None or p.case_id != c.id:
            raise err(404, "not_found", "not found")
        return {"url": signed_url(p.id)}


@router.post("/cases/{case_id}/demo_autofill")
def demo_autofill(case_id: str, request: Request) -> dict[str, Any]:
    """Demo clinics only: fill the remaining intake with the seeded synthetic answers (labeled simulated)."""
    from seed.scripts import SCRIPTS  # noqa: PLC0415
    with session_scope() as s:
        u = staff_user(request, s, ALL)
        c = clinic_case(s, u, case_id)
        clinic = s.get(Clinic, c.clinic_id)
        if not clinic.is_demo:
            raise err(403, "not_demo", "only on demo clinics")
        answers = SCRIPTS.get(c.id)
        if not answers:
            raise err(404, "no_script", "no synthetic answers for this case")
        if not cs.consent_given(s, c):
            answers = {"consent": True, **answers}
        written = simulate_answers(s, c, answers, actor=f"demo:{u.id}")
        return {"written": written}


# ---------------------------------------------------------------- admin

@router.get("/staff")
def list_staff(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("admin",))
        return {"staff": [{"id": x.id, "name": x.name, "email": x.email, "role": x.role, "active": x.active}
                          for x in s.scalars(select(StaffUser).where(StaffUser.clinic_id == u.clinic_id))]}


class NewStaff(BaseModel):
    name: str
    email: str
    role: str
    password: str


@router.post("/staff")
def invite_staff(body: NewStaff, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("admin",))
        if body.role not in ("intake", "reviewer", "admin"):
            raise err(400, "bad_role", "role must be intake, reviewer or admin")
        email = body.email.strip().lower()
        if s.scalars(select(StaffUser).where(StaffUser.email == email)).first():
            raise err(409, "exists", "email already registered")
        x = StaffUser(clinic_id=u.clinic_id, name=body.name, email=email, role=body.role,
                      password_hash=auth.hash_password(body.password))
        s.add(x)
        s.flush()
        cs.emit(s, None, "staff.invited", {"staff_id": x.id, "role": x.role}, "staff", u.id, clinic_id=u.clinic_id)
        return {"id": x.id}


class PatchStaff(BaseModel):
    role: str | None = None
    active: bool | None = None


@router.patch("/staff/{staff_id}")
def patch_staff(staff_id: str, body: PatchStaff, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("admin",))
        x = s.get(StaffUser, staff_id)
        if x is None or x.clinic_id != u.clinic_id:
            raise err(404, "not_found", "not found")
        if body.role:
            x.role = body.role
        if body.active is not None:
            x.active = body.active
        cs.emit(s, None, "staff.changed", {"staff_id": x.id, "role": x.role, "active": x.active}, "staff", u.id,
                clinic_id=u.clinic_id)
        return {"ok": True}


@router.get("/settings")
def get_settings(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("admin",))
        c = s.get(Clinic, u.clinic_id)
        from ...services.case_service import referral_card  # noqa: F401
        return {"name": c.name, "is_demo": c.is_demo, "settings": c.settings,
                "referral_defaults": {
                    "flag_continue": {"title": "Esto lo revisará una persona de su clínica"},
                    "stop_now": {"title": "Su clínica le va a contactar sobre esta parte",
                                 "body": "Esto debe revisarlo un profesional con licencia antes de presentar su "
                                         "solicitud. Ellis no puede aconsejarle sobre esto."}}}


class PatchSettings(BaseModel):
    name: str | None = None
    settings: dict[str, Any] | None = None


@router.patch("/settings")
def patch_settings(body: PatchSettings, request: Request) -> dict[str, Any]:
    with session_scope() as s:
        u = staff_user(request, s, ("admin",))
        c = s.get(Clinic, u.clinic_id)
        if body.name:
            c.name = body.name
        if body.settings:
            c.settings = {**(c.settings or {}), **body.settings}
        cs.emit(s, None, "clinic.settings_changed", {"keys": list((body.settings or {}).keys())}, "staff", u.id,
                clinic_id=c.id)
        return {"name": c.name, "settings": c.settings}


@router.get("/audit")
def audit(request: Request, format: str = "json", limit: int = 500):
    with session_scope() as s:
        u = staff_user(request, s, ("reviewer", "admin"))
        q = select(Event).where(Event.clinic_id == u.clinic_id).order_by(Event.id.desc()).limit(min(limit, 5000))
        if u.role == "reviewer":
            ids = [c.id for c in s.scalars(select(Case).where(Case.clinic_id == u.clinic_id,
                                                               Case.assigned_reviewer == u.id))]
            q = q.where(Event.case_id.in_(ids))
        rows = [{"id": e.id, "ts": e.ts.isoformat(), "case_id": e.case_id, "kind": e.kind, "actor_type": e.actor_type,
                 "actor": e.actor, "payload": e.payload} for e in s.scalars(q)]
        if format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["id", "ts", "case_id", "kind", "actor_type", "actor", "payload"])
            for r in rows:
                w.writerow([r["id"], r["ts"], r["case_id"], r["kind"], r["actor_type"], r["actor"], r["payload"]])
            return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                     headers={"Content-Disposition": "attachment; filename=ellis-audit.csv"})
        return {"events": rows}


@router.websocket("/stream")
async def stream(ws: WebSocket):
    payload = auth.unsign(ws.cookies.get(STAFF_COOKIE))
    if not payload or payload.get("kind") != "staff":
        await ws.close(code=4401)
        return
    def staff_clinic() -> str | None:
        with session_scope() as s:
            u = s.get(StaffUser, payload["staff_id"])
            return u.clinic_id if u else None
    clinic_id = await asyncio.to_thread(staff_clinic)
    if clinic_id is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    q = bus.subscribe(lambda m: m.get("clinic_id") == clinic_id and not m.get("transient"))
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=25)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "ping"})
                continue
            await ws.send_json({"type": msg["kind"], "case_id": msg.get("case_id"), "id": msg.get("id")})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(q)
