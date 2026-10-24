"""Phase 1 acceptance tests AT1–AT20 (spec: Seed data, demo script and acceptance tests)."""

import asyncio
import io
import json
from datetime import date

import pytest
from sqlalchemy import select, text

from ellis.db import (
    AgentRun, Briefing, Case, Document, Event, Fact, Flag, Gap, Job, Packet, ReviewItem, Signoff, StaffUser, Task,
    Utterance, VaultValue, session_scope,
)
from ellis.services import case_service as cs
from ellis.voice.client import InProcessClient
from ellis.voice.liaison import Liaison

H = {"Authorization": "Bearer test-secret"}


def tool(c, case, name, body=None):
    r = c.post(f"/tools/{name}", json=body or {}, headers={**H, "X-Ellis-Case": case})
    assert r.status_code == 200, r.text
    return r.json()


def consent(c, case="c_maria"):
    return tool(c, case, "record_fact", {"field": "consent", "value": True, "utterance_text": "Sí, de acuerdo."})


def maria_trip(c):
    consent(c)
    tool(c, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(c, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03",
                                       "utterance_text": "Salí el tres de agosto del 2023."})
    return tool(c, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True,
                                              "utterance_text": "Eh… creo que el tres de marzo… del veinticuatro."})


def _case(cid):
    with session_scope() as s:
        return s.get(Case, cid).state


# AT1 ---------------------------------------------------------------------------------------------------------
def test_at1_consent_first(client):
    r = client.post("/tools/record_fact", json={"field": "trips.any", "value": True},
                    headers={**H, "X-Ellis-Case": "c_maria"})
    assert r.json()["saved"] is False and r.json()["error"]["code"] == "consent_required"
    assert client.post("/api/a/session", json={"token": "demo-maria"}).status_code == 200
    consent(client)
    with session_scope() as s:
        assert s.scalars(select(Event).where(Event.case_id == "c_maria", Event.kind == "consent.given")).first()
    assert _case("c_maria") == "intake"


# AT2 ---------------------------------------------------------------------------------------------------------
def test_at2_disclosure_is_locked_and_holds_turns(seeded):
    lines = Liaison(InProcessClient("c_maria"), today=date(2026, 10, 23)).start()
    assert lines[0].kind == "disclosure" and lines[0].locked is True
    from ellis.api.routes.voice import VoiceSession

    async def run():
        vs = VoiceSession(ws=None, case_id="c_maria")
        vs.liaison = Liaison(InProcessClient("c_maria"), today=date(2026, 10, 23))
        vs.liaison.start()
        vs.current = {"id": "x", "locked": True, "done": asyncio.Event(), "interrupted": False}
        await vs.user_started()  # applicant talks over the locked line
        assert vs.current["interrupted"] is False
        await vs.turn("Sí")
        assert vs.held == ["Sí"]
        vs.closed = True
    asyncio.run(run())


# AT3 ---------------------------------------------------------------------------------------------------------
def test_at3_hedged_return_same_turn_flags(client):
    r = maria_trip(client)
    assert r["fact"]["status"] == "proposed" and r["fact"]["hedge"] is True
    assert r["derived"]["trip_days"] == 213
    cats = {f["category"] for f in r["flags"]}
    assert {"absence_gt_180", "date_conflict"} <= cats


# AT4 ---------------------------------------------------------------------------------------------------------
def test_at4_barge_in_correction(client):
    maria_trip(client)
    rb = tool(client, "c_maria", "read_back", {"field": "trips[0].return", "read_value": "applicant"})
    assert rb["value"] == "2024-03-03" and "tres de marzo" in rb["spoken"]
    r = tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-13",
                                                "interrupted_at_word": "tres",
                                                "utterance_text": "¡No, el trece! El trece de marzo."})
    assert r["fact"]["status"] == "confirmed" and r["fact"]["matches_document"]
    assert r["derived"]["trip_days"] == 223 and r["derived"]["presence_days"] == 1519
    assert r["resolved_flags"]
    with session_scope() as s:
        old = [f for f in s.scalars(select(Fact).where(Fact.case_id == "c_maria", Fact.field == "trips[0].return"))
               if f.value == "2024-03-03"][0]
        assert old.status == "superseded"
        ev = s.scalars(select(Event).where(Event.kind == "fact.corrected")).first()
        assert ev.payload["interrupted_at_word"] == "tres" and ev.payload["cause"] == "barge_in"
        assert not s.scalars(select(Flag).where(Flag.category == "date_conflict", Flag.status == "open")).all()
        assert s.scalars(select(Flag).where(Flag.category == "absence_gt_180", Flag.status == "open")).first()


# AT5 ---------------------------------------------------------------------------------------------------------
def test_at5_agents_run_after_correction(client, runner):
    with session_scope() as s:
        v0 = cs.latest_briefing_version(s, "c_maria")
    maria_trip(client)
    tool(client, "c_maria", "read_back", {"field": "trips[0].return", "read_value": "applicant"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-13"})
    runner.settle()
    with session_scope() as s:
        assert cs.latest_briefing_version(s, "c_maria") > v0
        qa = [t.title for t in s.scalars(select(Task).where(Task.case_id == "c_maria", Task.agent == "qa_reviewer"))]
        assert any("trip_days=223" in t for t in qa)
        assert not s.scalars(select(Fact).where(Fact.proposed_by.like("%@run_%"))).all()


# AT6 ---------------------------------------------------------------------------------------------------------
def test_at6_briefing_bump_mid_question(seeded):
    L = Liaison(InProcessClient("c_maria"), today=date(2026, 10, 23))
    L.start()
    L.handle("Sí, de acuerdo.")  # consent → read-back of lpr_since (v3 queue)
    with session_scope() as s:
        c = s.get(Case, "c_maria")
        b = cs.publish_briefing(s, c, {"queue": [{"kind": "read_back", "field": "dob", "read_value": "document",
                                                 "reason": "test"}]}, "case_manager@test")
        new_v = b.version
    L.handle("Sí.")  # answers lpr_since; the next item must come from the new briefing
    with session_scope() as s:
        ev = s.scalars(select(Event).where(Event.kind == "readback.started").order_by(Event.id.desc())).first()
        assert ev.payload["field"] == "dob" and ev.payload["briefing_version"] == new_v


# AT7 ---------------------------------------------------------------------------------------------------------
def test_at7_citation_flag_and_referral(client):
    consent(client)
    r = tool(client, "c_maria", "record_fact", {"field": "background.arrested_cited_detained", "value": "yes",
                                                "utterance_text": "una multa por exceso de velocidad"})
    assert any(f["category"] == "citation" for f in r["flags"])
    with session_scope() as s:
        ri = s.scalars(select(ReviewItem).where(ReviewItem.category == "citation")).all()
        assert len(ri) == 1 and ri[0].blocking
    client.post("/api/a/session", json={"token": "demo-maria"})
    cards = client.get("/api/a/case").json()["referrals"]
    assert any(c["variant"] == "flag_continue" and "Multa" in c["item"] for c in cards)


# AT8 ---------------------------------------------------------------------------------------------------------
def test_at8_stop_now(client):
    consent(client)
    L = Liaison(InProcessClient("c_maria"), today=date(2026, 10, 23))
    L.start()
    out = L.handle("No, porque me arrestaron por una pelea en 2016")
    assert out[0].kind == "stop" and out[0].locked
    with session_scope() as s:
        texts = [u.text for u in s.scalars(select(Utterance).where(Utterance.speaker == "applicant"))]
        assert "[STOP:arrest]" in texts
        ev = s.scalars(select(Event).where(Event.kind == "flag.raised")).all()
        stop_ev = [e for e in ev if e.payload.get("speed") == "stop_now"][0]
        assert set(stop_ev.payload) == {"flag_id", "speed", "section"}
        # no storage of the words anywhere
        for tbl in ("utterance", "event", "fact", "flag", "review_item", "task", "memo"):
            rows = s.execute(text(f"select * from {tbl}")).all()
            assert not any("pelea" in str(r) or "arrestaron" in str(r) for r in rows), tbl
    client.post("/api/clinic/login", json={"email": "dana@valle.demo", "password": "ellis-demo"})
    q = client.get("/api/clinic/review").json()["items"]
    stop = [i for i in q if i["speed"] == "stop_now"][0]
    assert stop["category"] == "arrest" and "facts" not in stop and q[0]["speed"] == "stop_now"
    from ellis.agents.context import build_context
    with session_scope() as s:
        ctx = build_context(s, s.get(Case, "c_maria"))
        assert [f for f in ctx["open_flags"] if f["speed"] == "stop_now"][0].keys() == {"flag_id", "speed", "section"}


# AT9 ---------------------------------------------------------------------------------------------------------
def test_at9_secure_entry_vault(client):
    client.post("/api/a/session", json={"token": "demo-ana"})
    r = client.post("/api/a/secure", json={"field": "a_number", "value": "A098765432"})
    assert r.status_code == 200
    from ellis.agents.context import build_context
    with session_scope() as s:
        f = cs.current_facts(s, "c_ana")["a_number"]
        assert f.value == "[A_NUMBER]" and s.get(VaultValue, f.id).ciphertext
        ctx = build_context(s, s.get(Case, "c_ana"))
        assert "A098765432" not in json.dumps(ctx) and ctx["facts"]["a_number"]["value"] == "[A_NUMBER]"
        brief = cs.liaison_briefing(s, s.get(Case, "c_ana"))
        assert "A098765432" not in json.dumps(brief, default=str)


# AT10 --------------------------------------------------------------------------------------------------------
def test_at10_spoken_digits_redacted(seeded):
    L = Liaison(InProcessClient("c_ana"), today=date(2026, 10, 23))
    L.start()
    out = L.handle("Es el cero nueve ocho siete seis cinco cuatro tres dos")
    assert out[0].kind == "secure_entry_repeat" and out[0].locked
    with session_scope() as s:
        u = s.scalars(select(Utterance).where(Utterance.speaker == "applicant")).all()[-1]
        assert u.redacted and "nueve" not in u.text


def _upload(case_id, name):
    from seed import specimens
    from ellis.services import documents as docs
    doc_type, data, _ = specimens.fixture_for(name)
    with session_scope() as s:
        d = docs.store_upload(s, s.get(Case, case_id), doc_type, name, data)
        did = d.id
    docs.extract_async(did)
    return did


# AT11 / AT12 / AT13 ------------------------------------------------------------------------------------------
def test_at11_to_at13_ana_documents(client, runner):
    tool(client, "c_ana", "record_fact", {"field": "lpr_since", "value": "2019-06", "hedge": True})
    tool(client, "c_ana", "record_fact", {"field": "names.used", "value": ["Ana Lucía Morales"]})
    _upload("c_ana", "ana_green_card_glare.png")
    runner.settle()
    with session_scope() as s:
        assert cs.current_facts(s, "c_ana")["lpr_since"].value == "2019-06"  # low quality never outranks
        q = cs.latest_briefing(s, "c_ana").body["queue"]
        assert q[0]["kind"] == "request_upload" and "reflejo" in q[0]["text_es"]
    _upload("c_ana", "ana_green_card_clear.png")
    runner.settle()
    with session_scope() as s:
        facts = cs.facts_for(s, "c_ana", "lpr_since")
        spoken = [f for f in facts if f.source == "spoken"][0]
        assert spoken.status == "disputed"
        # AT13: name mismatch computed in code, accent-insensitive
        nm = s.scalars(select(Flag).where(Flag.case_id == "c_ana", Flag.category == "name_mismatch")).first()
        assert nm is not None and nm.detail["given_match"] is True and nm.detail["family_match"] is False
    rb = tool(client, "c_ana", "read_back", {"field": "lpr_since"})
    assert rb["value"] == "2020-06-02" and rb["source"] == "document"
    r = tool(client, "c_ana", "record_fact", {"field": "lpr_since", "value": "2020-06-02"})
    assert r["fact"]["status"] == "confirmed"


# AT14 --------------------------------------------------------------------------------------------------------
def test_at14_mark_ready_blocked(client):
    maria_trip(client)
    client.post("/api/clinic/login", json={"email": "dana@valle.demo", "password": "ellis-demo"})
    r = client.post("/api/clinic/cases/c_maria/ready")
    assert r.status_code == 409
    codes = {f["code"] for f in r.json()["error"]["failing"]}
    assert {"blocking_review_items", "unconfirmed_fields", "qa_memo_missing"} <= codes


# AT15 / AT16 -------------------------------------------------------------------------------------------------
def test_at15_at16_signoff_packet_and_invalidation(seeded):
    from evals.flows import maria
    from pypdf import PdfReader
    x = maria()
    assert x.state() == "signed"
    with session_scope() as s:
        assert s.scalars(select(Signoff).where(Signoff.case_id == "c_maria", Signoff.valid.is_(True))).first()
        packets = s.scalars(select(Packet).where(Packet.case_id == "c_maria")).all()
        kinds = {p.kind for p in packets}
        assert {"n400_pdf", "online_copy_sheet", "evidence_index", "fee_sheet", "filing_checklist"} <= kinds
        for p in packets:
            txt = "".join(pg.extract_text() for pg in PdfReader(p.storage_path).pages)
            assert ("A123456789" in txt) == (p.kind == "n400_pdf"), p.kind
        fee = [p for p in packets if p.kind == "fee_sheet"][0]
        assert "710" in "".join(pg.extract_text() for pg in PdfReader(fee.storage_path).pages)
        c = s.get(Case, "c_maria")
        cs.record_fact(s, c, "contact.email", "maria@example.com", source="applicant_typed") if False else \
            cs.secure_entry(s, c, "contact.email", "maria@example.com")
    with session_scope() as s:
        assert s.get(Case, "c_maria").state == "review"
        assert not s.scalars(select(Signoff).where(Signoff.case_id == "c_maria", Signoff.valid.is_(True))).first()


# AT17 --------------------------------------------------------------------------------------------------------
def test_at17_cross_clinic_404(client):
    client.post("/api/clinic/login", json={"email": "staff@other.demo", "password": "ellis-demo"})
    assert client.get("/api/clinic/cases/c_maria").status_code == 404
    assert all(r["id"] != "c_maria" for r in client.get("/api/clinic/cases").json()["cases"])


# AT18 --------------------------------------------------------------------------------------------------------
def test_at18_rosa_engine(seeded):
    from seed.scripts import ROSA
    from ellis.rules import engine as E
    from ellis.config import rule_config
    facts = {k: v for k, v in ROSA.items() if k.startswith("trips[") or k == "filing.planned_date"}
    facts.update({"lpr_since": "2008-03-10", "dob": "1965-02-14"})
    out = E.evaluate(facts, date(2026, 10, 23), rule_config())
    assert out["presence_days"] == 1307 and out["exemptions"]["e55_15"] is True
    assert not [f for f in out["flags"] if f["category"].startswith("absence")]


# AT19 / AT20 -------------------------------------------------------------------------------------------------
def test_at19_invalid_output_twice(client):
    from ellis.agents.backends import FakeBackend
    from ellis.agents.runner import Runner
    consent(client)
    r = Runner(backend=FakeBackend([{"nonsense": 1}, "not even a dict"]), debounce_s=0)
    with session_scope() as s:
        s.add(Job(clinic_id="cl_valle", case_id="c_maria", agent="case_manager", status="queued", trigger_events=[]))
    before = _count(Briefing)
    r.drain()
    with session_scope() as s:
        j = s.scalars(select(Job).where(Job.agent == "case_manager").order_by(Job.id.desc())).first()
        assert j.status == "failed"
        assert s.scalars(select(Task).where(Task.title.like("Agent output invalid%"))).first()
    assert _count(Briefing) == before


def _count(model):
    with session_scope() as s:
        return len(s.scalars(select(model)).all())


def test_at20_duplicate_run_applied_once(client):
    from ellis.agents.proposals import apply_proposal, validate_envelope
    consent(client)
    env = {"agent": "doc_paralegal", "run_id": "run_dup1", "case_id": "c_maria", "items": [
        {"type": "gap", "payload": {"document_type": "court_record", "reason": "test", "key": "k1"}},
        {"type": "task", "payload": {"kind": "finding", "title": "dup test"}}]}
    with session_scope() as s:
        apply_proposal(s, validate_envelope(env, "doc_paralegal", "c_maria"))
    with session_scope() as s:
        res = apply_proposal(s, validate_envelope(env, "doc_paralegal", "c_maria"))
        assert res["duplicate"] is True
    with session_scope() as s:
        assert len(s.scalars(select(Task).where(Task.title == "dup test")).all()) == 1


@pytest.mark.parametrize("key,document_type", [
    ("flag:citation:", "court_record"),
    ("review:name_mismatch:full_name", "marriage_certificate"),
    ("doc:passport:", "passport"),
])
def test_gap_key_formats_store_and_close(client, key, document_type):
    from ellis.agents.proposals import apply_proposal, validate_envelope
    consent(client)
    with session_scope() as s:
        doc = Document(clinic_id="cl_valle", case_id="c_maria", document_type=document_type, filename="t.txt",
                       mime="text/plain", storage_path="t", sha256="abc", size=1, status="extracted")
        s.add(doc)
        s.flush()
        doc_id = doc.id
    run = "run_gap_" + key.replace(":", "_").replace("[", "").replace("]", "")
    opened = {"agent": "doc_paralegal", "run_id": run, "case_id": "c_maria", "items": [
        {"type": "gap", "payload": {"document_type": document_type, "reason": "needed", "label_es": "Documento",
                                    "key": key}}]}
    with session_scope() as s:
        res = apply_proposal(s, validate_envelope(opened, "doc_paralegal", "c_maria"))
    assert res["rejected"] == []
    assert any(item["type"] == "gap" for item in res["accepted"])
    with session_scope() as s:
        gap = s.scalars(select(Gap).where(Gap.case_id == "c_maria", Gap.key == key)).one()
        assert gap.status == "open"
    closed = {"agent": "doc_paralegal", "run_id": run + "_close", "case_id": "c_maria", "items": [
        {"type": "gap_close", "payload": {"key": key, "document_id": doc_id}}]}
    with session_scope() as s:
        res = apply_proposal(s, validate_envelope(closed, "doc_paralegal", "c_maria"))
    assert res["rejected"] == []
    assert any(item["type"] == "gap_close" for item in res["accepted"])
    with session_scope() as s:
        gap = s.scalars(select(Gap).where(Gap.case_id == "c_maria", Gap.key == key)).one()
        assert gap.status == "closed"
        assert gap.closed_by_document == doc_id


def test_authority_limits_reject_out_of_scope_items(client):
    from ellis.agents.proposals import apply_proposal, validate_envelope
    consent(client)
    env = {"agent": "docketing_clerk", "run_id": "run_auth", "case_id": "c_maria", "items": [
        {"type": "briefing", "payload": {"queue": []}},
        {"type": "deadline", "payload": {"kind": "made_up", "date_from_rule": "R-NOT-A-RULE"}}]}
    with session_scope() as s:
        res = apply_proposal(s, validate_envelope(env, "docketing_clerk", "c_maria"))
    assert len(res["rejected"]) == 2 and not res["accepted"]


# Flows -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("flow,expected", [("f1", "signed"), ("f2", "referred_out"), ("f3", "signed"), ("f4", "signed")])
def test_flows_end_to_end(seeded, flow, expected):
    from evals.flows import FLOWS
    x = FLOWS[flow]()
    assert x.state() == expected
    assert x.gate()["passes"]
