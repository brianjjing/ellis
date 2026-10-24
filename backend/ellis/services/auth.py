"""Auth: staff passwords (argon2), applicant link tokens (hashed, expiring), signed session cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import Case, CaseLink, now

_ph = PasswordHasher()
LINK_TTL = timedelta(hours=72)
LINK_IDLE = timedelta(days=30)
SESSION_TTL_S = 12 * 3600


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(h: str, pw: str) -> bool:
    try:
        return _ph.verify(h, pw)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_link(s: Session, case: Case, token: str | None = None) -> str:
    """Revokes old links and returns a fresh token (shown once; stored hashed)."""
    for old in s.scalars(select(CaseLink).where(CaseLink.case_id == case.id, CaseLink.revoked.is_(False))):
        old.revoked = True
    token = token or secrets.token_urlsafe(32)
    s.add(CaseLink(clinic_id=case.clinic_id, case_id=case.id, token_hash=token_hash(token),
                   issued_at=now(), expires_at=now() + LINK_TTL))
    s.flush()
    return token


def resolve_link(s: Session, token: str) -> tuple[CaseLink | None, str | None]:
    """(link, error) where error is 'expired' | 'invalid'."""
    link = s.scalars(select(CaseLink).where(CaseLink.token_hash == token_hash(token))).first()
    if link is None or link.revoked:
        return None, "invalid"
    t = now()
    exp = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=t.tzinfo)
    last = link.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=t.tzinfo)
    # expires 72 h after issue unless used; then 30 days after last use
    if last is None and t > exp:
        return None, "expired"
    if last is not None and t > last + LINK_IDLE:
        return None, "expired"
    link.last_used_at = t
    link.opened = True
    return link, None


def link_status(link: CaseLink | None) -> str:
    if link is None or link.revoked:
        return "none"
    t = now()
    exp = link.expires_at if link.expires_at.tzinfo else link.expires_at.replace(tzinfo=t.tzinfo)
    if not link.opened and t > exp:
        return "expired"
    return "active" if link.opened else "never_opened"


# ---------------------------------------------------------------- signed cookies

def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict) -> str:
    payload = {**payload, "exp": int(time.time()) + SESSION_TTL_S}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def unsign(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, mac = token.rsplit(".", 1)
    good = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64(good), mac):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:  # noqa: BLE001
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


# ---------------------------------------------------------------- rate limit (10/min/IP)

_hits: dict[str, deque] = defaultdict(deque)


def rate_limited(key: str, limit: int = 10, window_s: int = 60) -> bool:
    q = _hits[key]
    t = time.time()
    while q and q[0] < t - window_s:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(t)
    return False
