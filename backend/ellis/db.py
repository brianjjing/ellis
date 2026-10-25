"""Database models (SQLAlchemy 2). Postgres 16 in production; SQLite works for zero-setup dev and tests.

Every case-scoped table carries clinic_id and case_id; row-level filters are enforced in the API layer.
The event table is append-only (the API never updates or deletes it; on Postgres, revoke update/delete).
"""

from __future__ import annotations

import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, event as sa_event, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session

from .config import settings

JSONType = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


class Base(DeclarativeBase):
    pass


class Clinic(Base):
    __tablename__ = "clinic"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("cl"))
    name: Mapped[str] = mapped_column(String(200))
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StaffUser(Base):
    __tablename__ = "staff_user"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("su"))
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # intake | reviewer | admin
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Account(Base):
    """An applicant login. Staff keep their own table; one email belongs to at most one of the two."""
    __tablename__ = "account"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ac"))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(300))
    active_case_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("c"))
    clinic_id: Mapped[str] = mapped_column(ForeignKey("clinic.id"), index=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en-US")
    state: Mapped[str] = mapped_column(String(30), default="consent_pending")
    sub_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # patient_mode, ...
    assigned_reviewer: Mapped[str | None] = mapped_column(ForeignKey("staff_user.id"), nullable=True)
    disclosure_version: Mapped[str] = mapped_column(String(20), default="es-1")
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # bump on material fact changes; QA memo must be newer than this for the gate
    material_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("account.id"), nullable=True, index=True)

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name[:1]}."


class Invitation(Base):
    """A clinic's invitation to an applicant account, matched by email. Nothing moves until accepted."""
    __tablename__ = "invitation"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("iv"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    email: Mapped[str] = mapped_column(String(200), index=True)
    invited_by: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted | declined
    case_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseLink(Base):
    __tablename__ = "case_link"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lk"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    opened: Mapped[bool] = mapped_column(Boolean, default=False)


class CallSession(Base):
    __tablename__ = "session"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("s"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    briefing_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    third_party_present: Mapped[bool] = mapped_column(Boolean, default=False)
    third_party_relation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="voice")  # voice | text | line


class Utterance(Base):
    __tablename__ = "utterance"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("u"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    speaker: Mapped[str] = mapped_column(String(20))  # applicant | liaison
    text: Mapped[str] = mapped_column(Text)  # text only, never audio; stop-now turns are [STOP:<category>]
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Fact(Base):
    __tablename__ = "fact"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("f"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    field: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)  # masked token for vault fields
    status: Mapped[str] = mapped_column(String(20))  # proposed | confirmed | disputed | superseded
    source: Mapped[str] = mapped_column(String(20))  # spoken | document | applicant_typed | derived | staff_typed
    hedge: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSONType, default=dict)  # utterance_id | document_id | rule_run_id | staff_user_id
    proposed_by: Mapped[str] = mapped_column(String(80), default="applicant")
    supersedes: Mapped[str | None] = mapped_column(String(40), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    third_party: Mapped[bool] = mapped_column(Boolean, default=False)
    matches_document: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VaultValue(Base):
    __tablename__ = "vault_value"
    fact_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[str] = mapped_column(String(120))
    ciphertext: Mapped[str] = mapped_column(Text)  # AES-GCM, base64(nonce|ct)
    last4: Mapped[str | None] = mapped_column(String(8), nullable=True)


class Event(Base):
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinic_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    case_id: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)  # never sensitive values
    actor_type: Mapped[str] = mapped_column(String(20))  # applicant | liaison | agent | staff | system
    actor: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Document(Base):
    __tablename__ = "document"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("d"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(60))
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="extracting")  # extracting | extracted | failed
    quality: Mapped[str | None] = mapped_column(String(10), nullable=True)
    checks: Mapped[dict] = mapped_column(JSONType, default=dict)
    exhibit: Mapped[str | None] = mapped_column(String(4), nullable=True)
    uploaded_by: Mapped[str] = mapped_column(String(80), default="applicant")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Extraction(Base):
    __tablename__ = "extraction"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("x"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id"), index=True)
    data: Mapped[dict] = mapped_column(JSONType)  # identifiers already moved to vault (masked tokens)
    quality: Mapped[str] = mapped_column(String(10))
    quality_reasons: Mapped[list] = mapped_column(JSONType, default=list)
    extractor: Mapped[str] = mapped_column(String(40))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Briefing(Base):
    __tablename__ = "briefing"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("b"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONType)
    proposed_by: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Task(Base):
    __tablename__ = "task"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("t"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # finding | question | challenge | system
    title: Mapped[str] = mapped_column(Text)  # internal (clinic) text
    title_es: Mapped[str | None] = mapped_column(Text, nullable=True)  # applicant-safe one-liner
    field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done
    round: Mapped[int] = mapped_column(Integer, default=1)
    proposed_by: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Flag(Base):
    __tablename__ = "flag"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fl"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    speed: Mapped[str] = mapped_column(String(20))  # stop_now | flag_continue
    layer: Mapped[int] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    section: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)  # never stop-now words
    applicant_label_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    applicant_self_report: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReviewItem(Base):
    __tablename__ = "review_item"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ri"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    flag_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category: Mapped[str] = mapped_column(String(40))
    speed: Mapped[str] = mapped_column(String(20))
    field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed | case_blocked
    resolution_required: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    facts_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_notes: Mapped[list] = mapped_column(JSONType, default=list)
    evidence: Mapped[list] = mapped_column(JSONType, default=list)  # document ids
    decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applicant_note_shown: Mapped[bool] = mapped_column(Boolean, default=False)
    proposed_by: Mapped[str] = mapped_column(String(80), default="case_api")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Derived(Base):
    __tablename__ = "derived"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("r"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    data: Mapped[dict] = mapped_column(JSONType)
    rule_config_version: Mapped[str] = mapped_column(String(30))
    inputs_hash: Mapped[str] = mapped_column(String(40))
    computed_by: Mapped[str] = mapped_column(String(80), default="case_api")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Deadline(Base):
    __tablename__ = "deadline"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("dl"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60))
    date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    date_from_rule: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    proposed_by: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Memo(Base):
    __tablename__ = "memo"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("m"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # status | qa | note
    body_md: Mapped[str] = mapped_column(Text)
    proposed_by: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Gap(Base):
    __tablename__ = "gap"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("g"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    label_es: Mapped[str | None] = mapped_column(Text, nullable=True)
    key: Mapped[str] = mapped_column(String(80))  # dedupe key
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | closed | applicant_declined
    closed_by_document: Mapped[str | None] = mapped_column(String(40), nullable=True)
    review_item_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    proposed_by: Mapped[str] = mapped_column(String(80))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentRun(Base):
    __tablename__ = "agent_run"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # run_id
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    backend: Mapped[str] = mapped_column(String(20))
    trigger_events: Mapped[list] = mapped_column(JSONType, default=list)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(40), nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    accepted_items: Mapped[list] = mapped_column(JSONType, default=list)
    rejected_items: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="running")
    ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clinic_id: Mapped[str] = mapped_column(String(40))
    case_id: Mapped[str] = mapped_column(String(40), index=True)
    agent: Mapped[str] = mapped_column(String(40), index=True)
    trigger_event: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger_events: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued | running | done | failed
    run_id: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Signoff(Base):
    __tablename__ = "signoff"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("so"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    typed_name: Mapped[str] = mapped_column(String(200))
    attestation_version: Mapped[str] = mapped_column(String(20))
    section_confirmations: Mapped[dict] = mapped_column(JSONType, default=dict)
    fact_ids: Mapped[list] = mapped_column(JSONType, default=list)
    facts_hash: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_aloud: Mapped[bool] = mapped_column(Boolean, default=False)
    assisted_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Packet(Base):
    __tablename__ = "packet"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("p"))
    clinic_id: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str] = mapped_column(String(200))
    storage_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    built_from_fact_versions: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="current")  # current | stale | stale_fee
    signoff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ---------------------------------------------------------------- engine / sessions

_engine = None
_SessionLocal = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.database_url
        kw: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kw["pool_size"] = 10
            kw["max_overflow"] = 20
        _engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @sa_event.listens_for(_engine, "connect")
            def _pragma(dbapi_con, _):  # pragma: no cover - sqlite only
                cur = dbapi_con.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def is_postgres() -> bool:
    return engine().dialect.name == "postgresql"


def create_all() -> None:
    Base.metadata.create_all(engine())
    if is_postgres():
        with engine().begin() as con:
            con.execute(text("ALTER TABLE cases ADD COLUMN IF NOT EXISTS account_id VARCHAR(40)"))
            con.execute(text("CREATE INDEX IF NOT EXISTS ix_cases_account_id ON cases (account_id)"))
            # NOTIFY case_events on every event insert (LISTEN case_events for cross-process consumers).
            con.execute(text("""
                create or replace function notify_event() returns trigger as $$
                begin
                  perform pg_notify('case_events', json_build_object(
                    'case', new.case_id, 'kind', new.kind, 'id', new.id)::text);
                  return new;
                end $$ language plpgsql;
            """))
            con.execute(text("drop trigger if exists t_notify on event"))
            con.execute(text(
                "create trigger t_notify after insert on event for each row execute function notify_event()"))


def drop_all() -> None:
    Base.metadata.drop_all(engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    with session_scope() as s:
        yield s
