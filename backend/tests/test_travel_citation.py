"""Travel candidates and citation validation (proposals.py + case_service.py)."""

import pytest
from sqlalchemy import select

from ellis.db import Fact, TravelCandidate, ReviewItem, Task, session_scope
from ellis.agents.proposals import apply_proposal, Envelope, Item, AUTHORITY
from ellis.services import case_service as cs


def _env(case_id, items, agent="doc_paralegal"):
    return Envelope(agent=agent, run_id=f"run_{case_id}_test", case_id=case_id,
                    items=[Item(type=t, payload=p) for t, p in items])


def _consent(s, case):
    cs.record_fact(s, case, "consent", True, actor="test", actor_type="applicant")


# ---------------------------------------------------------------- travel_candidate

def test_travel_candidate_stored_as_candidate_not_fact(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        env = _env(case.id, [("travel_candidate", {
            "trip_index": 0, "departure_date": "2023-03-15", "return_date": "2023-04-10",
            "departure_source": "passport_stamp", "return_source": "i94",
            "source_document_ids": [], "note": None,
        })])
        result = apply_proposal(s, env)
        accepted_types = [a["type"] for a in result["accepted"]]
        assert "travel_candidate" in accepted_types
        # must NOT be in the facts table
        assert not list(s.scalars(select(Fact).where(Fact.case_id == case.id, Fact.field.like("trips[%]"))))
        # must be in travel_candidate table
        tc = s.scalars(select(TravelCandidate).where(TravelCandidate.case_id == case.id)).first()
        assert tc is not None
        assert tc.departure_date == "2023-03-15" and tc.return_date == "2023-04-10"
        assert tc.departure_source == "passport_stamp" and tc.return_source == "i94"
        assert tc.status == "pending"


def test_travel_candidate_invalid_source_rejected(seeded):
    with session_scope() as s:
        from ellis.db import Case
        from pydantic import ValidationError
        case = s.get(Case, "c_maria")
        _consent(s, case)
        with pytest.raises(ValidationError):
            apply_proposal(s, _env(case.id, [("travel_candidate", {
                "trip_index": 0, "departure_date": "2023-03-15",
                "departure_source": "not_a_valid_source", "return_source": "i94",
            })]))


def test_travel_candidate_deduped_by_trip_index(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        payload = {"trip_index": 1, "departure_date": "2022-07-01", "return_date": "2022-08-01",
                   "departure_source": "i94", "return_source": "i94", "source_document_ids": []}
        env1 = Envelope(agent="doc_paralegal", run_id="run_dedup_1", case_id=case.id,
                        items=[Item(type="travel_candidate", payload=payload)])
        apply_proposal(s, env1)
        env2 = Envelope(agent="doc_paralegal", run_id="run_dedup_2", case_id=case.id,
                        items=[Item(type="travel_candidate", payload=payload)])
        result2 = apply_proposal(s, env2)
        # second run: item is skipped (pending candidate already exists), but not rejected
        assert all(a["type"] != "travel_candidate" for a in result2["accepted"])
        assert not result2["rejected"]
        assert len(list(s.scalars(select(TravelCandidate).where(TravelCandidate.case_id == case.id,
                                                                 TravelCandidate.trip_index == 1)))) == 1


def test_confirmed_travel_candidate_becomes_voice_fact_via_record_fact(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        # Plant a pending travel candidate
        apply_proposal(s, _env(case.id, [("travel_candidate", {
            "trip_index": 2, "departure_date": "2024-06-15", "return_date": "2024-07-20",
            "departure_source": "passport_stamp", "return_source": "passport_stamp",
            "source_document_ids": [],
        })]))
        # Applicant confirms departure date by voice (existing record_fact path)
        r = cs.record_fact(s, case, "trips[2].departure", "2024-06-15", source="voice", actor="liaison",
                           actor_type="liaison")
        assert r["saved"] is True
        fact = cs.current_facts(s, case.id).get("trips[2].departure")
        assert fact is not None and fact.source == "voice" and fact.value == "2024-06-15"


# ---------------------------------------------------------------- travel candidate in briefing queue

def test_pending_travel_candidate_appears_in_briefing_queue(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        apply_proposal(s, _env(case.id, [("travel_candidate", {
            "trip_index": 0, "departure_date": "2023-01-10", "return_date": None,
            "departure_source": "i94", "return_source": "missing", "source_document_ids": [],
        })]))
        briefing = cs.get_briefing(s, case)
        candidates_in_queue = [it for it in briefing["queue"] if it.get("kind") == "read_back_candidate"]
        assert len(candidates_in_queue) == 1
        assert candidates_in_queue[0]["departure_date"] == "2023-01-10"
        assert candidates_in_queue[0]["is_candidate"] is True


def test_confirmed_departure_removes_candidate_from_briefing_queue(seeded):
    """pending_item() with kind=read_back_candidate returns False once the departure is confirmed."""
    from ellis.services.case_service import pending_item
    candidate_item = {
        "kind": "read_back_candidate", "trip_index": 3,
        "departure_date": "2022-01-10", "return_date": None,
        "departure_source": "i94", "return_source": "missing",
    }
    # When the departure field is absent from view: pending
    view_empty: dict = {}
    assert pending_item(view_empty, candidate_item) is True

    # When the departure is present but not confirmed: still pending
    view_proposed = {"trips[3].departure": {"value": "2022-01-10", "status": "proposed"}}
    assert pending_item(view_proposed, candidate_item) is True

    # When the departure is confirmed: no longer pending → removed from queue
    view_confirmed = {"trips[3].departure": {"value": "2022-01-10", "status": "confirmed"}}
    assert pending_item(view_confirmed, candidate_item) is False


# ---------------------------------------------------------------- citation

def test_citation_on_allowed_domain_kept(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        env = _env(case.id, [("review_item", {
            "category": "document_conflict", "field": "trips[0].departure",
            "note": "departure date disagrees with passport",
            "citation": {"rule": "8 CFR 316.5", "url": "https://www.ecfr.gov/current/title-8/section-316.5",
                         "retrieved_at": "2026-10-24", "quote": "continuous residence means an uninterrupted period"},
        })])
        apply_proposal(s, env)
        ri = s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id,
                                                 ReviewItem.category == "document_conflict")).first()
        assert ri is not None and ri.citation is not None
        assert ri.citation["rule"] == "8 CFR 316.5"
        assert "ecfr.gov" in ri.citation["url"]


def test_citation_on_disallowed_domain_dropped_item_kept(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        env = _env(case.id, [("review_item", {
            "category": "document_conflict", "field": "trips[0].departure",
            "note": "departure date disagrees with passport",
            "citation": {"rule": "blog post", "url": "https://immigrationblog.example.com/article",
                         "retrieved_at": "2026-10-24", "quote": "five years"},
        })])
        result = apply_proposal(s, env)
        # review_item accepted, citation dropped
        assert any(a["type"] == "review_item" for a in result["accepted"])
        assert any(r["type"] == "citation" for r in result["rejected"])
        ri = s.scalars(select(ReviewItem).where(ReviewItem.case_id == case.id,
                                                 ReviewItem.category == "document_conflict")).first()
        assert ri is not None and ri.citation is None


def test_citation_quote_over_25_words_dropped(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        long_quote = " ".join(["word"] * 26)
        env = _env(case.id, [("task", {
            "title": "Check residence period", "kind": "finding",
            "citation": {"rule": "INA 316(a)", "url": "https://uscis.gov/n400",
                         "retrieved_at": "2026-10-24", "quote": long_quote},
        })])
        result = apply_proposal(s, env)
        assert any(a["type"] == "task" for a in result["accepted"])
        assert any(r["type"] == "citation" for r in result["rejected"])
        t = s.scalars(select(Task).where(Task.case_id == case.id)).first()
        assert t is not None and t.citation is None


def test_valid_citation_on_task_kept(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        env = _env(case.id, [("task", {
            "title": "Verify continuous residence requirement", "kind": "finding",
            "citation": {"rule": "INA 316(a)", "url": "https://uscis.gov/n400",
                         "retrieved_at": "2026-10-24", "quote": "must have resided continuously in the US for five years"},
        })])
        result = apply_proposal(s, env)
        assert any(a["type"] == "task" for a in result["accepted"])
        assert not any(r["type"] == "citation" for r in result["rejected"])
        t = s.scalars(select(Task).where(Task.case_id == case.id)).first()
        assert t is not None and t.citation is not None
        assert t.citation["rule"] == "INA 316(a)"


# ---------------------------------------------------------------- non_issue

def test_non_issue_accepted(seeded):
    with session_scope() as s:
        from ellis.db import Case
        case = s.get(Case, "c_maria")
        _consent(s, case)
        env = _env(case.id, [("non_issue", {"field": "full_name", "note": "name matches green card exactly"})])
        result = apply_proposal(s, env)
        assert any(a["type"] == "non_issue" for a in result["accepted"])
