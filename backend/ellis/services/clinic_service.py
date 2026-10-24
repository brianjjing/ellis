"""Clinic-side helpers: branding, reviewer names, staff lookups."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..db import Case, Clinic, StaffUser


def clinic_of(s: Session, case: Case) -> Clinic:
    return s.get(Clinic, case.clinic_id)


def clinic_phone(s: Session, case: Case) -> str | None:
    c = clinic_of(s, case)
    return (c.settings or {}).get("phone") if c else None


def reviewer_first_name(s: Session, case: Case) -> str | None:
    if not case.assigned_reviewer:
        return None
    u = s.get(StaffUser, case.assigned_reviewer)
    return u.name.split()[0] if u else None


def referral_overrides(s: Session, case: Case) -> dict:
    c = clinic_of(s, case)
    return (c.settings or {}).get("referral_text", {}) if c else {}
