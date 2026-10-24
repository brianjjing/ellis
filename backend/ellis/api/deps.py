"""Request auth helpers for the three surfaces: liaison tools, applicant client, clinic client."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Case, StaffUser
from ..services import auth

APPLICANT_COOKIE = "ellis_a"
STAFF_COOKIE = "ellis_s"


def err(status: int, code: str, message: str, field: str | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "field": field})


def tool_case(request: Request, s: Session) -> Case:
    """Line agent: Authorization: Bearer $ELLIS_TOOL_SECRET + X-Ellis-Case (baked via constant_value)."""
    authz = request.headers.get("authorization", "")
    if not authz.startswith("Bearer ") or not hmac.compare_digest(authz[7:], settings.tool_secret):
        raise err(401, "unauthorized", "bad tool secret")
    case_id = request.headers.get("x-ellis-case")
    case = s.get(Case, case_id) if case_id else None
    if case is None:
        raise err(404, "not_found", "case not found")
    return case


def applicant_case(request: Request, s: Session) -> Case:
    payload = auth.unsign(request.cookies.get(APPLICANT_COOKIE))
    if not payload or payload.get("kind") != "applicant":
        raise err(401, "unauthorized", "open your link again")
    case = s.get(Case, payload["case_id"])
    if case is None:
        raise err(404, "not_found", "case not found")
    return case


def staff_user(request: Request, s: Session, roles: tuple[str, ...] | None = None) -> StaffUser:
    payload = auth.unsign(request.cookies.get(STAFF_COOKIE))
    if not payload or payload.get("kind") != "staff":
        raise err(401, "unauthorized", "sign in")
    u = s.get(StaffUser, payload["staff_id"])
    if u is None or not u.active:
        raise err(401, "unauthorized", "sign in")
    if roles and u.role not in roles:
        raise err(403, "forbidden", f"requires role {', '.join(roles)}")
    return u


def clinic_case(s: Session, staff: StaffUser, case_id: str) -> Case:
    """Every clinic query is scoped by clinic_id; another clinic's case is a 404."""
    case = s.get(Case, case_id)
    if case is None or case.clinic_id != staff.clinic_id:
        raise err(404, "not_found", "case not found")
    return case
