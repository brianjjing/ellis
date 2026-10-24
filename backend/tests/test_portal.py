"""Applicant accounts, invitations, guest chat and the independent clinic."""

import pytest

from ellis.db import Account, StaffUser, session_scope
from ellis.services import accounts
from ellis.services.accounts import AccountError


def test_create_account_and_independent_case(seeded):
    with session_scope() as s:
        acct = accounts.create_account(s, "Ana Pérez", "ana@x.test", "password1")
        case = accounts.create_independent_case(s, acct)
        assert case.clinic_id == "cl_independent"
        assert (case.first_name, case.last_name) == ("Ana", "Pérez")
        assert case.account_id == acct.id
        assert accounts.active_case(s, acct).id == case.id
        assert accounts.is_independent(case)
        assert [c.id for c in accounts.cases_for(s, acct)] == [case.id]


def test_email_unique_across_staff_and_accounts(seeded):
    with session_scope() as s:
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Dana", "dana@valle.demo", "password1")
        assert e.value.status == 409
        accounts.create_account(s, "Ana", "Ana@X.test ", "password1")
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana 2", "ana@x.test", "password1")
        assert e.value.status == 409


def test_weak_password_rejected(seeded):
    with session_scope() as s:
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana", "ana@x.test", "short")
        assert e.value.code == "weak_password"
        with pytest.raises(AccountError) as e:
            accounts.create_account(s, "Ana", "nope", "password1")
        assert e.value.code == "bad_email"


def test_authenticate_both_kinds(seeded):
    with session_scope() as s:
        accounts.create_account(s, "Ana Pérez", "ana@x.test", "password1")
    with session_scope() as s:
        assert isinstance(accounts.authenticate(s, "ana@x.test", "password1"), Account)
        assert isinstance(accounts.authenticate(s, "dana@valle.demo", "ellis-demo"), StaffUser)
        assert accounts.authenticate(s, "ana@x.test", "wrong") is None
        assert accounts.authenticate(s, "nobody@x.test", "password1") is None
        s.query(StaffUser).filter_by(email="dana@valle.demo").one().active = False
        s.flush()
        assert accounts.authenticate(s, "dana@valle.demo", "ellis-demo") is None


# ---------------------------------------------------------------- Task 2: unified auth routes

def signup(client, name="Ana Pérez", email="ana@x.test", password="password1", **extra):
    return client.post("/api/auth/signup", json={"kind": "applicant", "name": name, "email": email,
                                                  "password": password, **extra})


def login(client, email, password="ellis-demo"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_signup_applicant_sets_cookie(client):
    r = signup(client)
    assert r.status_code == 200 and r.json()["kind"] == "applicant"
    c = client.get("/api/a/case")
    assert c.status_code == 200 and c.json()["clinic"]["name"] == "Independent"


def test_signup_clinic_creates_admin(client):
    r = client.post("/api/auth/signup", json={"kind": "clinic", "name": "Lu Admin", "email": "lu@casa.test",
                                              "password": "password1", "clinic_name": "Casa Legal"})
    assert r.status_code == 200 and r.json()["kind"] == "staff"
    me = client.get("/api/clinic/me").json()
    assert me["role"] == "admin" and me["clinic"]["name"] == "Casa Legal"
    assert client.get("/api/clinic/cases").json()["cases"] == []
    r = client.post("/api/auth/signup", json={"kind": "clinic", "name": "X", "email": "x@casa.test",
                                              "password": "password1"})
    assert r.status_code == 400


def test_login_routes_by_role(client):
    assert login(client, "dana@valle.demo").json()["kind"] == "staff"
    assert client.get("/api/auth/me").json()["kind"] == "staff"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json() == {"kind": "guest"}


def test_login_replaces_other_role(client):
    signup(client)
    login(client, "dana@valle.demo")
    assert client.get("/api/auth/me").json()["kind"] == "staff"
    assert client.get("/api/a/case").status_code == 401
    login(client, "ana@x.test", "password1")
    me = client.get("/api/auth/me").json()
    assert me["kind"] == "applicant" and me["account"]["email"] == "ana@x.test"
    assert client.get("/api/clinic/me").status_code == 401


def test_wrong_password_401(client):
    r = login(client, "dana@valle.demo", "nope-nope")
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"


def test_demo_applicant_login(client):
    r = login(client, "maria@valle.demo")
    assert r.status_code == 200 and r.json()["case_id"] == "c_maria"


# ---------------------------------------------------------------- Tasks 4 and 7: guest guide and carry-over

STOP_PHRASE = "No, porque me arrestaron por una pelea en 2016"


def test_guest_asks_then_estimates(client):
    from datetime import date
    from ellis.config import rule_config
    from ellis.rules.engine import earliest_filing
    r = client.post("/api/guest/chat", json={"messages": [], "answers": {}}).json()
    assert "permanent resident" in r["reply"]
    r = client.post("/api/guest/chat", json={"messages": [{"who": "you", "text": "since March 4 2021"}],
                                             "answers": {}}).json()
    assert r["answers"]["lpr_since"] == "2021-03-04"
    assert r["estimate"]["earliest_filing"] == earliest_filing(date(2021, 3, 4), rule_config()).isoformat()


def test_guest_stop_topic(client):
    from ellis.services.guest import STOP_REPLY
    r = client.post("/api/guest/chat", json={"messages": [{"who": "you", "text": STOP_PHRASE}]}).json()
    assert r["stop"] is True and r["reply"] == STOP_REPLY


def test_guest_writes_nothing(client):
    from sqlalchemy import func, select
    from ellis.db import CallSession, Event, Utterance
    def counts():
        with session_scope() as s:
            return [s.scalar(select(func.count()).select_from(t)) for t in (Event, Utterance, CallSession)]
    before = counts()
    for text in ("hi", "since 2021", "yes"):
        client.post("/api/guest/chat", json={"messages": [{"who": "you", "text": text}]})
    assert counts() == before


def test_prefill_applied_on_consent(client):
    from ellis.db import Case
    from ellis.services import case_service as cs
    signup(client, guest={"answers": {"lpr_since": "2021-03-04", "married_to_citizen": True}, "transcript": []})
    case_id = client.get("/api/auth/me").json()["case_id"]
    with session_scope() as s:
        case = s.get(Case, case_id)
        assert "lpr_since" not in cs.current_facts(s, case.id)
        cs.record_fact(s, case, "consent", True)
        facts = cs.current_facts(s, case.id)
        assert facts["lpr_since"].value == "2021-03-04" and facts["lpr_since"].hedge
        assert facts["marital.status"].value == "married"


def test_guest_import_redacts(client):
    from sqlalchemy import select
    from ellis.db import CallSession, Utterance
    signup(client, guest={"answers": {}, "transcript": [
        {"who": "you", "text": STOP_PHRASE}, {"who": "ellis", "text": "ok"},
        {"who": "you", "text": "my A number is 123456789"}]})
    case_id = client.get("/api/auth/me").json()["case_id"]
    with session_scope() as s:
        texts = [u.text for u in s.scalars(select(Utterance).where(Utterance.case_id == case_id))]
        assert any("[STOP:" in t for t in texts) and not any("123456789" in t for t in texts)
        assert s.scalars(select(CallSession).where(CallSession.case_id == case_id)).one().channel == "guest"


def test_bad_prefill_values_dropped(client):
    from ellis.db import Case
    signup(client, guest={"answers": {"lpr_since": "yesterday", "hack": 1}, "transcript": []})
    with session_scope() as s:
        assert s.get(Case, client.get("/api/auth/me").json()["case_id"]).settings.get("prefill") in (None, {})
