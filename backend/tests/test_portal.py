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
    assert "2 questions" in r["reply"]
    assert "lpr_since" not in r["answers"]
    # A date before the visitor opts in is not stored.
    early = client.post("/api/guest/chat", json={"messages": [{"who": "you", "text": "since March 4 2021"}],
                                                 "answers": {}}).json()
    assert "lpr_since" not in early["answers"]
    r = client.post("/api/guest/chat", json={"messages": [{"who": "you", "text": "yes"}], "answers": {}}).json()
    assert "Resident since" in r["reply"] and r["answers"]["check"] == "yes"
    r = client.post("/api/guest/chat", json={
        "messages": [{"who": "you", "text": "yes"}, {"who": "ellis", "text": r["reply"]},
                     {"who": "you", "text": "since March 4 2021"}],
        "answers": r["answers"]}).json()
    assert r["answers"]["lpr_since"] == "2021-03-04"
    assert r["estimate"]["earliest_filing"] == earliest_filing(date(2021, 3, 4), rule_config()).isoformat()


def test_guest_bug_conversation_no_key():
    from datetime import date
    from ellis.services.guest import respond
    today = date(2026, 10, 23)
    first = respond([{"who": "you", "text": "hi, how does the process work?"}], {}, today)
    assert "2 questions" in first["reply"]
    assert "green card is fine" not in first["reply"].lower()
    assert "lpr_since" not in first["answers"]
    second = respond([
        {"who": "you", "text": "hi, how does the process work?"},
        {"who": "ellis", "text": first["reply"]},
        {"who": "you", "text": "how do you know what the date on my green card is"},
    ], first["answers"], today)
    assert second["reply"] != first["reply"]
    assert "don't know" in second["reply"].lower()
    assert "asking" in second["reply"].lower()
    assert "resident since" in second["reply"].lower()


def test_guest_bug_conversation_model(monkeypatch):
    from datetime import date
    from ellis.services import guest
    seen = {"n": 0, "first": ""}

    def fake(messages, answers, language):
        seen["n"] += 1
        if seen["n"] == 1:
            seen["first"] = ("You and a clinic prepare the application in a few short sessions. "
                             "Want me to check where you stand? I'll ask 2 questions. Your answers stay in this "
                             "browser until you make an account.")
            return seen["first"]
        return seen["first"]

    monkeypatch.setattr(guest, "model_configured", lambda: True)
    monkeypatch.setattr(guest, "complete_with_model", fake)
    today = date(2026, 10, 23)
    first = guest.respond([{"who": "you", "text": "hi, how does the process work?"}], {}, today)
    assert "2 questions" in first["reply"]
    assert seen["n"] == 1
    second = guest.respond([
        {"who": "you", "text": "hi, how does the process work?"},
        {"who": "ellis", "text": first["reply"]},
        {"who": "you", "text": "how do you know what the date on my green card is"},
    ], first["answers"], today)
    assert second["reply"] != first["reply"]
    assert "don't know" in second["reply"].lower()
    assert seen["n"] == 2


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


# ---------------------------------------------------------------- Task 3: clinic links into accounts

def new_clinic_case(client) -> tuple[str, str]:
    login(client, "dana@valle.demo")
    r = client.post("/api/clinic/cases", json={"first_name": "Lia", "last_name": "Mora"}).json()
    client.post("/api/auth/logout")
    return r["case"]["id"], r["link"].rsplit("/a/", 1)[1]


def test_signup_with_link_attaches_without_independent_case(client):
    case_id, token = new_clinic_case(client)
    assert client.get(f"/api/auth/link/{token}").json()["first_name"] == "Lia"
    r = signup(client, link_token=token)
    assert r.json()["case_id"] == case_id
    with session_scope() as s:
        acct = s.query(Account).filter_by(email="ana@x.test").one()
        assert [c.id for c in accounts.cases_for(s, acct)] == [case_id]


def test_extraction_pending_until_consent(seeded):
    from sqlalchemy import select
    from ellis.db import Case, Document, Fact
    from ellis.services import case_service as cs
    from ellis.services import documents as docs
    with session_scope() as s:
        case = s.get(Case, "c_rosa")
        assert not cs.consent_given(s, case)
        doc = Document(clinic_id=case.clinic_id, case_id=case.id, document_type="green_card", filename="x.png",
                       mime="image/png", storage_path="x", sha256="a" * 64, size=1, status="extracted",
                       uploaded_by="test")
        s.add(doc)
        s.flush()
        assert docs._apply_doc_fact(s, case, doc, "lpr_since", "2018-01-02", "high") is True
        assert s.scalars(select(Fact).where(Fact.case_id == case.id, Fact.field == "lpr_since")).first() is None
        assert (case.settings or {})["prefill"]["extracted"]["lpr_since"]["value"] == "2018-01-02"
        cs.record_fact(s, case, "consent", True, actor="test", actor_type="applicant")
        assert cs.current_facts(s, case.id)["lpr_since"].value == "2018-01-02"


def test_stop_now_pending_until_consent(seeded):
    from sqlalchemy import select
    from ellis.db import Case, Fact
    from ellis.services import case_service as cs
    with session_scope() as s:
        case = s.get(Case, "c_rosa")
        res = cs.stop_now(s, case, "arrest", 4)
        assert res["deferred"] == []
        rows = list(s.scalars(select(Fact).where(Fact.case_id == case.id)))
        assert not any(f.value == cs.catalog.DEFERRED for f in rows)
        assert (case.settings or {}).get("pending_deferrals")
        cs.record_fact(s, case, "consent", True, actor="test", actor_type="applicant")
        rows = list(s.scalars(select(Fact).where(Fact.case_id == case.id)))
        assert any(f.value == cs.catalog.DEFERRED for f in rows)


def test_evaluate_rules_skips_without_consent(seeded):
    from ellis.db import Case
    from ellis.services import case_service as cs
    with session_scope() as s:
        case = s.get(Case, "c_rosa")
        assert cs.evaluate_rules(s, case) == (None, [], [])


def test_activity_sentence_and_unknown(seeded):
    from ellis.db import Event
    from ellis.services.activity import describe
    with session_scope() as s:
        known = Event(clinic_id="cl_valle", case_id="c_rosa", kind="fact.recorded",
                      payload={"field": "lpr_since"}, actor_type="liaison", actor="liaison")
        assert describe(s, known) == "Client liaison saved Resident since."
        unknown = Event(clinic_id="cl_valle", case_id="c_rosa", kind="widget.spun",
                        payload={"field": "not_a_field"}, actor_type="system", actor="case_api")
        assert unknown.kind and describe(s, unknown).startswith("Case updated:")


def test_activity_voice_fact(seeded):
    """A fact saved by the applicant voice session."""
    from ellis.db import Event
    from ellis.services.activity import describe
    with session_scope() as s:
        ev = Event(clinic_id="cl_valle", case_id="c_rosa", kind="fact.recorded",
                   payload={"field": "marital.status"}, actor_type="applicant", actor="applicant")
        sentence = describe(s, ev)
        assert sentence == "Client saved Marital status."


def test_activity_correction(seeded):
    """A fact confirmation by the liaison (read-back approved)."""
    from ellis.db import Event
    from ellis.services.activity import describe
    with session_scope() as s:
        ev = Event(clinic_id="cl_valle", case_id="c_rosa", kind="fact.confirmed",
                   payload={"field": "lpr_since"}, actor_type="liaison", actor="liaison")
        sentence = describe(s, ev)
        assert sentence == "Client liaison confirmed Resident since."


def test_activity_document_upload(seeded):
    """A document uploaded by a staff member."""
    from ellis.db import Event
    from ellis.services.activity import describe
    with session_scope() as s:
        ev = Event(clinic_id="cl_valle", case_id="c_rosa", kind="doc.uploaded",
                   payload={"document_type": "green_card"}, actor_type="staff", actor="staff")
        sentence = describe(s, ev)
        assert "uploaded" in sentence.lower()


def test_activity_unknown_kind_uses_label(seeded):
    """An event kind not in the template dict falls back to a readable label."""
    from ellis.db import Event
    from ellis.services.activity import describe
    with session_scope() as s:
        ev = Event(clinic_id="cl_valle", case_id="c_rosa", kind="future.thing",
                   payload={}, actor_type="system", actor="case_api")
        sentence = describe(s, ev)
        assert sentence.startswith("Case updated:")
        # The label is title-cased, not a raw key with dots
        assert "future.thing" not in sentence


def test_logged_in_link_attach_and_taken(client):
    case_id, token = new_clinic_case(client)
    signup(client)
    assert client.post("/api/a/link", json={"token": token}).status_code == 200
    assert client.get("/api/auth/me").json()["case_id"] == case_id
    with session_scope() as s:
        assert len(accounts.cases_for(s, s.query(Account).filter_by(email="ana@x.test").one())) == 2
    client.post("/api/auth/logout")
    signup(client, email="bo@x.test")
    r = client.post("/api/a/link", json={"token": token})
    assert r.status_code == 409 and r.json()["error"]["message"] == accounts.LINK_TAKEN
