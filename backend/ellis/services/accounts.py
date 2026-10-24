"""Applicant accounts: signup, login across applicants and staff, and the self-serve independent case."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import Account, CallSession, Case, Clinic, StaffUser, Utterance, now
from . import auth
from . import case_service as cs
from . import keywords

INDEPENDENT_ID = "cl_independent"
MIN_PASSWORD = 8


class AccountError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def email_taken(s: Session, email: str) -> bool:
    e = _norm(email)
    return (s.scalar(select(Account.id).where(Account.email == e)) is not None
            or s.scalar(select(StaffUser.id).where(func.lower(StaffUser.email) == e)) is not None)


def independent_clinic(s: Session) -> Clinic:
    c = s.get(Clinic, INDEPENDENT_ID)
    if c is None:
        c = Clinic(id=INDEPENDENT_ID, name="Independent", is_demo=False, settings={})
        s.add(c)
        s.flush()
    return c


def check_new_identity(s: Session, email: str, password: str) -> str:
    """Validates a new login (applicant or staff) and returns the normalized email."""
    e = _norm(email)
    if "@" not in e:
        raise AccountError(400, "bad_email", "Enter a valid email address.")
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(400, "weak_password", f"Use at least {MIN_PASSWORD} characters for your password.")
    if email_taken(s, e):
        raise AccountError(409, "exists", "An account with that email already exists.")
    return e


def create_account(s: Session, name: str, email: str, password: str) -> Account:
    e = check_new_identity(s, email, password)
    acct = Account(email=e, name=(name or "").strip(), password_hash=auth.hash_password(password), created_at=now())
    s.add(acct)
    s.flush()
    return acct


def authenticate(s: Session, email: str, password: str) -> Account | StaffUser | None:
    e = _norm(email)
    acct = s.scalars(select(Account).where(Account.email == e)).first()
    if acct is not None:
        return acct if auth.verify_password(acct.password_hash, password) else None
    staff = s.scalars(select(StaffUser).where(func.lower(StaffUser.email) == e)).first()
    if staff is not None and staff.active and auth.verify_password(staff.password_hash, password):
        return staff
    return None


def create_independent_case(s: Session, acct: Account, language: str = "en-US") -> Case:
    independent_clinic(s)
    first, _, last = acct.name.strip().partition(" ")
    case = Case(clinic_id=INDEPENDENT_ID, account_id=acct.id, first_name=first, last_name=last.strip(),
                language=language, state="consent_pending", created_by=acct.id, created_at=now())
    s.add(case)
    s.flush()
    cs.emit(s, case, "case.created", {"by": acct.id, "independent": True}, "applicant", acct.id)
    cs.publish_briefing(s, case, {"queue": []}, proposed_by="case_api")
    acct.active_case_id = case.id
    return case


def cases_for(s: Session, acct: Account) -> list[Case]:
    return list(s.scalars(select(Case).where(Case.account_id == acct.id).order_by(Case.created_at.desc())))


def active_case(s: Session, acct: Account) -> Case | None:
    if acct.active_case_id:
        c = s.get(Case, acct.active_case_id)
        if c is not None and c.account_id == acct.id:
            return c
    cases = cases_for(s, acct)
    return cases[0] if cases else None


def applicant_cookie(acct: Account | None, case: Case) -> str:
    return auth.sign({"kind": "applicant", "case_id": case.id, **({"account_id": acct.id} if acct else {})})


def is_independent(case: Case) -> bool:
    return case.clinic_id == INDEPENDENT_ID


# ---------------------------------------------------------------- guest work carried into a new account

def save_prefill(s: Session, case: Case, answers: dict) -> None:
    """Keeps only known guest answers with valid values; they become hedged facts once consent is given."""
    keep: dict = {}
    v = (answers or {}).get("lpr_since")
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", v):
        keep["lpr_since"] = v
    if isinstance((answers or {}).get("married_to_citizen"), bool):
        keep["married_to_citizen"] = answers["married_to_citizen"]
    if keep:
        case.settings = {**(case.settings or {}), "prefill": keep}


def apply_prefill(s: Session, case: Case) -> int:
    settings = dict(case.settings or {})
    pre = settings.pop("prefill", None) or {}
    case.settings = settings
    facts = []
    if pre.get("lpr_since"):
        facts.append(("lpr_since", pre["lpr_since"]))
    if pre.get("married_to_citizen") is True:
        facts += [("marital.status", "married"), ("spouse.citizenship_status", "us_citizen")]
    saved = 0
    for field, value in facts:
        try:
            cs.record_fact(s, case, field, value, hedge=True, source="spoken", actor="guest_import",
                           actor_type="system", provenance={"guest": True})
            saved += 1
        except cs.CaseError:
            pass
    return saved


def import_guest_transcript(s: Session, case: Case, transcript: list[dict]) -> str | None:
    """The guest chat becomes the first conversation. Stop-list turns stored as [STOP:<cat>], numbers redacted."""
    if not transcript:
        return None
    t = now()
    sess = CallSession(clinic_id=case.clinic_id, case_id=case.id, started_at=t, ended_at=t, channel="guest")
    s.add(sess)
    s.flush()
    for m in transcript[:200]:
        text, redacted = (m.get("text") or "")[:2000], False
        you = m.get("who") == "you"
        if you and (cat := keywords.stop_hit(text)):
            text, redacted = f"[STOP:{cat}]", True
        elif keywords.has_sensitive_number(text):
            text, redacted = keywords.redact_numbers(text), True
        s.add(Utterance(clinic_id=case.clinic_id, case_id=case.id, session_id=sess.id,
                        speaker="applicant" if you else "liaison", text=text, redacted=redacted, ts=t))
    s.flush()
    return sess.id


# ---------------------------------------------------------------- clinic links claimed into accounts

LINK_TAKEN = "This link belongs to another account. Ask your clinic for help."


def _link_case(s: Session, token: str) -> Case:
    link, problem = auth.resolve_link(s, token)
    if problem == "expired":
        raise AccountError(410, "link_expired", "This link has expired. Ask your clinic for a new one.")
    if link is None:
        raise AccountError(404, "link_invalid", "This link isn't valid. Ask your clinic for a new one.")
    return s.get(Case, link.case_id)


def link_preview(s: Session, token: str) -> dict:
    case = _link_case(s, token)
    clinic = s.get(Clinic, case.clinic_id)
    out = {"first_name": case.first_name, "last_name": case.last_name, "clinic_name": clinic.name,
           "taken": case.account_id is not None}
    s.rollback()  # resolve_link marks the link used; a preview mustn't
    return out


def attach_link(s: Session, acct: Account, token: str) -> Case:
    case = _link_case(s, token)
    if case.account_id and case.account_id != acct.id:
        raise AccountError(409, "link_taken", LINK_TAKEN)
    case.account_id = acct.id
    acct.active_case_id = case.id
    cs.emit(s, case, "link.opened", {}, "applicant", acct.id)
    cs.emit(s, case, "account.attached", {"account_id": acct.id}, "applicant", acct.id)
    return case
