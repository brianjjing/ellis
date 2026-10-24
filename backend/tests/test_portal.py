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
