"""One door for everyone (/api/auth/*): applicant and clinic sign-up, login, logout, and who-am-I."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from ...db import Account, Case, Clinic, StaffUser, now, session_scope
from ...services import accounts, auth, case_service as cs
from ..deps import APPLICANT_COOKIE, STAFF_COOKIE, err
from .clinic import me_payload

router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = dict(httponly=True, samesite="lax", max_age=12 * 3600)


def _limit(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    if auth.rate_limited(f"auth:{ip}", limit=20):
        raise err(429, "rate_limited", "Too many tries. Please wait a minute.")


def set_applicant(response: Response, acct: Account | None, case: Case) -> None:
    response.set_cookie(APPLICANT_COOKIE, accounts.applicant_cookie(acct, case), **COOKIE)
    response.delete_cookie(STAFF_COOKIE)


def set_staff(response: Response, u: StaffUser) -> None:
    response.set_cookie(STAFF_COOKIE, auth.sign({"kind": "staff", "staff_id": u.id}), **COOKIE)
    response.delete_cookie(APPLICANT_COOKIE)


def applicant_me(acct: Account | None, case: Case) -> dict[str, Any]:
    return {"kind": "applicant", "case_id": case.id,
            "account": {"id": acct.id, "name": acct.name, "email": acct.email} if acct else None}


def me_of(request: Request, s) -> dict[str, Any]:
    """Staff cookie wins if both are somehow present and valid."""
    p = auth.unsign(request.cookies.get(STAFF_COOKIE))
    u = s.get(StaffUser, p["staff_id"]) if p and p.get("kind") == "staff" else None
    if u is not None and u.active:
        return {"kind": "staff", **me_payload(s, u)}
    p = auth.unsign(request.cookies.get(APPLICANT_COOKIE))
    case = s.get(Case, p["case_id"]) if p and p.get("kind") == "applicant" else None
    if case is not None:
        acct = s.get(Account, p["account_id"]) if p.get("account_id") else None
        return applicant_me(acct, case)
    return {"kind": "guest"}


class Turn(BaseModel):
    who: Literal["you", "ellis"]
    text: str


class Guest(BaseModel):
    answers: dict[str, Any] = {}
    transcript: list[Turn] = []


class SignupReq(BaseModel):
    kind: Literal["applicant", "clinic"]
    name: str
    email: str
    password: str
    clinic_name: str | None = None
    guest: Guest | None = None


@router.post("/signup")
def signup(body: SignupReq, request: Request, response: Response) -> dict[str, Any]:
    _limit(request)
    with session_scope() as s:
        try:
            if body.kind == "clinic":
                if not (body.clinic_name or "").strip():
                    raise accounts.AccountError(400, "clinic_name", "Enter your clinic's name.")
                return _signup_clinic(s, body, response)
            acct = accounts.create_account(s, body.name, body.email, body.password)
            # ponytail: link_token attach (Task 3) not built yet.
            case = accounts.create_independent_case(s, acct)
            if body.guest:
                accounts.save_prefill(s, case, body.guest.answers)
                accounts.import_guest_transcript(s, case, [t.model_dump() for t in body.guest.transcript])
        except accounts.AccountError as e:
            raise err(e.status, e.code, e.message) from None
        set_applicant(response, acct, case)
        return applicant_me(acct, case)


def _signup_clinic(s, body: SignupReq, response: Response) -> dict[str, Any]:
    e = accounts.check_new_identity(s, body.email, body.password)
    c = Clinic(name=body.clinic_name.strip(), is_demo=False,
               settings={"phone": None, "retention": {"transcripts_days": 90, "closed_case_delete_days": 90},
                         "referral_text": {}, "handles_categories": ["arrest", "removal", "citizenship_claim",
                                                                     "fraud", "danger"]})
    s.add(c)
    s.flush()
    u = StaffUser(clinic_id=c.id, name=body.name.strip(), email=e, role="admin",
                  password_hash=auth.hash_password(body.password), created_at=now())
    s.add(u)
    s.flush()
    cs.emit(s, None, "clinic.created", {"staff_id": u.id}, "staff", u.id, clinic_id=c.id)
    set_staff(response, u)
    return {"kind": "staff", **me_payload(s, u)}


class LoginReq(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginReq, request: Request, response: Response) -> dict[str, Any]:
    _limit(request)
    with session_scope() as s:
        who = accounts.authenticate(s, body.email, body.password)
        if who is None:
            raise err(401, "bad_credentials", "Wrong email or password.")
        if isinstance(who, StaffUser):
            set_staff(response, who)
            cs.emit(s, None, "staff.login", {"staff_id": who.id}, "staff", who.id, clinic_id=who.clinic_id)
            return {"kind": "staff", **me_payload(s, who)}
        case = accounts.active_case(s, who) or accounts.create_independent_case(s, who)
        set_applicant(response, who, case)
        return applicant_me(who, case)


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(APPLICANT_COOKIE)
    response.delete_cookie(STAFF_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    with session_scope() as s:
        return me_of(request, s)
