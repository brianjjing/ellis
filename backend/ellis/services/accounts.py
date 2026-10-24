"""Applicant accounts: signup, login across applicants and staff, and the self-serve independent case."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import Account, Case, Clinic, StaffUser, now
from . import auth
from . import case_service as cs

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
