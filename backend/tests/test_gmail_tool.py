"""Gmail MCP tooling (case_manager escalation-send, doc_paralegal inbox-search-on-hedge): what's
testable without a live Creao + Gmail run, and what still needs one.

Covered here, with real code, no guessing:
  - the wake trigger (runner.wakes): a hedged OR confirmed trips[].departure/return fact wakes
    doc_paralegal; an unrelated date field (dob) does not.
  - the authority change letting doc_paralegal propose a "question"-kind task (the Gmail-candidate ->
    read-back path), and that applying one only ever creates a Task row, never a Fact -- proving a
    found candidate can't become a confirmed fact without the liaison's own read_back/record_fact flow.
  - backends._translate()'s parsing of a *fenced-JSON chatText block*, for both doc_paralegal's
    existing items and case_manager's new escalation-sent memo -- against a fixture, not a live run.

NOT covered, and can't be without connecting the real thing (see bottom of file for how):
  - whether doc_paralegal's Creao playbook actually calls its Gmail MCP and in what shape it reports
    a found candidate.
  - whether case_manager's Creao playbook actually sends a real email to the clinic's own inbox.
  - whether the playbook text correctly skips the search/send when it shouldn't.
"""

from sqlalchemy import select

from ellis.agents.backends import _translate
from ellis.agents.proposals import AUTHORITY, apply_proposal, validate_envelope
from ellis.agents.runner import wakes
from ellis.db import Case, Event, Fact, Job, Task, session_scope

from test_acceptance import consent, tool

H = {"Authorization": "Bearer test-secret"}


# ---------------------------------------------------------------------------------------------- wake trigger

def _ev(kind, payload):
    return Event(id=1, case_id="c_maria", clinic_id="cl_valle", kind=kind, payload=payload, actor_type="applicant")


def test_hedged_trip_date_wakes_doc_paralegal():
    assert "doc_paralegal" in wakes(_ev("fact.recorded", {"field": "trips[0].return", "hedge": True}))


def test_confirmed_trip_date_also_wakes_doc_paralegal():
    # wakes() doesn't gate on hedge itself -- build_context() already carries each fact's hedge flag
    # (ellis/agents/context.py:26), so whether to actually search is the agent's own call, not the
    # router's. This just confirms the router reliably wakes it either way.
    assert "doc_paralegal" in wakes(_ev("fact.recorded", {"field": "trips[0].departure", "hedge": False}))


def test_unrelated_date_field_does_not_wake_doc_paralegal_via_the_new_rule():
    # dob is a date field too (so this isn't testing "any date wakes it") but it's not a trip date.
    out = wakes(_ev("fact.recorded", {"field": "dob", "hedge": True}))
    assert "doc_paralegal" not in out


def test_hedged_return_date_queues_a_real_doc_paralegal_job(client, runner):
    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True})
    runner.dispatch_new_events()
    with session_scope() as s:
        job = s.scalars(select(Job).where(Job.case_id == "c_maria", Job.agent == "doc_paralegal")).first()
        assert job is not None and job.status == "queued"


# ---------------------------------------------------------------------------------------- authority + apply

def test_doc_paralegal_may_propose_a_question_task():
    assert "question" in AUTHORITY["doc_paralegal"]["task_kinds"]


def test_gmail_candidate_becomes_a_task_never_a_fact(client):
    # ASSUMED shape for what doc_paralegal's Creao engine would emit after finding a candidate date by
    # searching the client's inbox -- a "task"/"question" item in its existing chatText JSON block,
    # same mechanism as every other item it already proposes. Confirm this cannot write ellis.db.Fact
    # directly -- only a Task row, so the applicant must still confirm it by voice (read_back).
    consent(client)
    env = {"agent": "doc_paralegal", "run_id": "run_gmail_1", "case_id": "c_maria", "items": [
        {"type": "task", "payload": {"kind": "question", "field": "trips[0].departure",
                                      "title": "Possible departure date found in email",
                                      "question_es": "Encontré un correo que menciona el 3 de agosto, "
                                                     "¿es correcto?"}}]}
    with session_scope() as s:
        before = len(s.scalars(select(Fact).where(Fact.case_id == "c_maria", Fact.field == "trips[0].departure"))
                     .all())
        res = apply_proposal(s, validate_envelope(env, "doc_paralegal", "c_maria"))
    assert res["rejected"] == []
    assert any(item["type"] == "task" for item in res["accepted"])
    with session_scope() as s:
        after = len(s.scalars(select(Fact).where(Fact.case_id == "c_maria", Fact.field == "trips[0].departure"))
                    .all())
        t = s.scalars(select(Task).where(Task.case_id == "c_maria", Task.kind == "question",
                                         Task.field == "trips[0].departure")).first()
        assert after == before  # no new Fact -- it's a candidate, not a confirmation
        assert t is not None and t.question_es.startswith("Encontré")


# ---------------------------------------------------------------------------------- _translate() parsing

_GMAIL_CANDIDATE_CHAT = """Here's what I found.

```json
{"items": [{"type": "task", "kind": "question", "field": "trips[0].departure",
            "title": "Possible departure date found in email",
            "question_es": "Encontré un correo..."}]}
```
"""

_ESCALATION_SENT_CHAT = """Escalated to the clinic.

```json
{"items": [{"type": "memo", "kind": "status",
            "body_md": "Escalation emailed to the clinic's own inbox: subject 'Needs attorney review: c_maria'."}]}
```
"""


def test_translate_doc_paralegal_gmail_candidate():
    items = _translate("doc_paralegal", {"chatText": _GMAIL_CANDIDATE_CHAT}, H, "es")
    assert items == [{"type": "task", "payload": {"kind": "question", "field": "trips[0].departure",
                                                   "title": "Possible departure date found in email",
                                                   "question_es": "Encontré un correo..."}}]


def test_translate_case_manager_escalation_memo(monkeypatch):
    # no question_queue.json artifact this run -- just the escalation memo in chatText
    items = _translate("case_manager", {"chatText": _ESCALATION_SENT_CHAT, "artifacts": []}, H, "es")
    assert items == [{"type": "memo", "payload": {
        "kind": "status",
        "body_md": "Escalation emailed to the clinic's own inbox: subject 'Needs attorney review: c_maria'."}}]


def test_translate_case_manager_unaffected_when_chat_has_no_json(monkeypatch):
    # today's real shape: case_manager's chatText is plain prose, only the artifact carries items.
    # Confirms the new chatText parsing is additive -- same output as before this change.
    monkeypatch.setattr("ellis.agents.backends._fetch_json", lambda headers, url: {"questions": [
        {"field": "trips[0].return", "text": "¿Cuándo regresó?", "why": "missing"}]})
    result = {"chatText": "Reviewed the case, nothing urgent.",
              "artifacts": [{"title": "question_queue.json", "url": "https://x/questions.json"}]}
    items = _translate("case_manager", result, H, "es")
    assert items == [{"type": "briefing", "payload": {"queue": [
        {"kind": "ask", "field": "trips[0].return", "question_es": "¿Cuándo regresó?", "reason": "missing"}]}}]


def test_translate_case_manager_combines_chat_memo_and_artifact_briefing(monkeypatch):
    monkeypatch.setattr("ellis.agents.backends._fetch_json", lambda headers, url: {"questions": []})
    result = {"chatText": _ESCALATION_SENT_CHAT,
              "artifacts": [{"title": "question_queue.json", "url": "https://x/questions.json"}]}
    items = _translate("case_manager", result, H, "es")
    assert [it["type"] for it in items] == ["memo", "briefing"]


def test_case_manager_may_send_a_status_memo():
    assert AUTHORITY["case_manager"]["memo_kinds"] == {"status"}


# ---------------------------------------------------------------------------------------------------------
# What still needs a real Creao + Gmail MCP run, and how to do it once the dashboard connectors are live:
#
# 1. Hedged-date search actually fires: give a real case a hedged trips[].departure/return (voice or
#    tool(client, "c_maria", "record_fact", {..., "hedge": True})), then call
#    CreaoBackend().run("doc_paralegal", build_context(...), run_id) directly (bypass the dispatcher/
#    debounce) and print the raw result.chatText -- confirm the Gmail MCP was actually invoked and see
#    the real shape it reports a candidate in, so _translate()/the fixtures above can be corrected to
#    match reality instead of the assumed shape used here.
# 2. Negative case: same run against a case with a *confirmed* (non-hedged) trip date -- the playbook
#    should skip the Gmail search entirely. If it searches anyway, fix the playbook text first.
# 3. Escalation send: trigger whatever condition case_manager's playbook uses to decide an escalation is
#    needed, run it the same way, and check the clinic's own Gmail inbox for the real email -- then
#    confirm the run's chatText/memo matches what actually happened (don't just trust the agent's prose).
# 4. Negative case for escalation: a run where no escalation is warranted should send nothing.
# 5. Once 1-4 are confirmed, update _GMAIL_CANDIDATE_CHAT / _ESCALATION_SENT_CHAT above (and _translate()
#    if the real shape differs) to match the live result, so this file stops being speculative.


# ------------------------------------------------------------------------------------------ consent gate
# Our own rough wiring (ellis/services/case_service.py:_maybe_search_email_for_hedged_trips) -- consent
# recorded -> search (MockGmailService by default, no OAuth needed) -> a read-back question Task. This
# runs entirely in our backend, independent of whether a Creao agent ever calls its own Gmail tool.

def test_consent_without_hedged_trip_does_nothing(client):
    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": True})
    with session_scope() as s:
        assert s.scalars(select(Task).where(Task.proposed_by == "gmail_search_tool")).first() is None


def test_consent_with_hedged_trip_creates_a_question_task(client):
    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True})
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": True})
    with session_scope() as s:
        t = s.scalars(select(Task).where(Task.case_id == "c_maria", Task.proposed_by == "gmail_search_tool",
                                         Task.field == "trips[0].return")).first()
        assert t is not None and t.kind == "question" and t.question_es
        assert s.scalars(select(Fact).where(Fact.case_id == "c_maria", Fact.field == "trips[0].return",
                                            Fact.status == "confirmed")).first() is None  # still a candidate


def test_consent_with_hedged_trip_actually_reaches_the_live_briefing(client):
    # The real bug this guards against: a bare Task row never reaches the liaison. case_team_asks
    # (views.py:365) only ever reads the latest published Briefing's queue -- this confirms the
    # read_back item actually lands there and survives get_briefing's pending_item filter.
    from ellis.services import case_service as cs

    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True})
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": True})
    with session_scope() as s:
        case = s.get(Case, "c_maria")
        briefing = cs.get_briefing(s, case)
        item = next((it for it in briefing["queue"] if it.get("field") == "trips[0].return"
                    and it.get("kind") == "read_back"), None)
        assert item is not None, f"not in live queue: {briefing['queue']}"
        assert "email" in item.get("reason", "")


def test_consent_does_not_duplicate_the_task_on_repeat(client):
    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True})
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": True})
    with session_scope() as s:
        n = len(s.scalars(select(Task).where(Task.case_id == "c_maria", Task.proposed_by == "gmail_search_tool"))
               .all())
        assert n == 1


def test_declining_consent_creates_no_task(client):
    consent(client)
    tool(client, "c_maria", "record_fact", {"field": "trips.any", "value": True})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].departure", "value": "2023-08-03"})
    tool(client, "c_maria", "record_fact", {"field": "trips[0].return", "value": "2024-03-03", "hedge": True})
    tool(client, "c_maria", "record_fact", {"field": "email_search_consent", "value": False})
    with session_scope() as s:
        assert s.scalars(select(Task).where(Task.proposed_by == "gmail_search_tool")).first() is None
