"""Agent backends. All return a proposal envelope (dict) for the same context.

- skeleton:  deterministic Python (no model, no credits) — the default until keys/agents exist
- anthropic: prompts/<agent>.md + context → Claude → JSON envelope
- creao:     POST to the agent's own Creao app, poll to completion, translate its real output into
  our proposal envelope. See docs/superpowers/specs/2026-10-24-creao-canonical-fields-design.md.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import Any

import httpx

from ..config import BACKEND_DIR, PROMPTS_DIR, settings
from . import skeleton


class BackendError(Exception):
    pass


def fresh_recompute(ctx: dict) -> dict:
    """QA recomputes in a fresh process from raw facts (independent of the API process's cached config)."""
    facts = {k: v["value"] for k, v in ctx["facts"].items() if v["value"] != "deferred_to_professional"
             and not str(v["value"]).startswith("[")}
    code = ("import json,sys,datetime;from ellis.rules import engine as E;from ellis.config import rule_config;"
            "d=json.load(sys.stdin);print(json.dumps(E.evaluate(d['facts'],"
            "datetime.date.fromisoformat(d['today']),rule_config())))")
    try:
        p = subprocess.run([sys.executable, "-c", code], input=json.dumps({"facts": facts, "today": ctx["today"]}),
                           capture_output=True, text=True, timeout=20, cwd=str(BACKEND_DIR),
                           env={**os.environ, "PYTHONPATH": str(BACKEND_DIR)})
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        from ..rules import engine as E
        from ..config import rule_config
        from datetime import date
        return E.evaluate(facts, date.fromisoformat(ctx["today"]), rule_config())


class SkeletonBackend:
    name = "skeleton"
    model = None

    def run(self, agent: str, ctx: dict, run_id: str, error: str | None = None) -> dict:
        fn = skeleton.AGENTS[agent]
        items = fn(ctx, recompute=lambda: fresh_recompute(ctx)) if agent == "qa_reviewer" else fn(ctx)
        return {"agent": agent, "run_id": run_id, "case_id": ctx["case"]["id"],
                "based_on_event_id": ctx.get("latest_event_id"), "items": items}


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        self.model = model or settings.agent_model

    def run(self, agent: str, ctx: dict, run_id: str, error: str | None = None) -> dict:
        import anthropic  # optional dependency
        prompt = (PROMPTS_DIR / f"{agent}.md").read_text(encoding="utf-8")
        user = ("Context (JSON; identifiers are masked tokens):\n" + json.dumps(ctx, default=str)[:150000] +
                f"\n\nReturn ONLY the proposal envelope JSON with agent=\"{agent}\", run_id=\"{run_id}\", "
                f"case_id=\"{ctx['case']['id']}\", based_on_event_id={ctx.get('latest_event_id')}. "
                f"Write applicant-facing text (fields ending in _es) in "
                f"{'Spanish' if ctx.get('language') == 'es' else 'English'}; _es is only the field name.")
        if error:
            user += f"\n\nYour previous output was invalid: {error}\nFix it and return valid JSON only."
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(model=self.model, max_tokens=4000, system=prompt,
                                     messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        start, end = text.find("{"), text.rfind("}")
        if start < 0:
            raise BackendError("no JSON object in model output")
        return json.loads(text[start:end + 1])


# The three Creao engines (case_master.py, docket_engine.py, qa_review.py) each look up a different
# set of canonical field names; our own field keys (config/fields.yaml) match none of them exactly.
# Two live runs (case_manager run_live_test_1, qa_reviewer run_live_qa_1, both 2026-10-24) scored false
# criticals until these were aliased -- both agents self-diagnosed the mismatch and named the canonical
# keys they needed, rather than silently failing.
_CANONICAL_ALIASES = {
    "lpr_since": ["date_lpr", "date_became_lpr"],
    "dob": ["date_of_birth"],
    "a_number": ["alien_number"],
    "sex": ["gender"],
    "marital.status": ["marital_status"],
}


def _to_case_bundle(ctx: dict) -> dict:
    """Reshape our internal context into the "tolerant" bundle shape the Creao playbooks expect
    (CASE_PACKET_CONTRACT.md / DOCKET_CONTRACT.md: every section optional). Minimal, not exhaustive --
    just enough for a real run against live case data instead of a synthetic fixture."""
    facts = []
    for k, v in ctx["facts"].items():
        row = {"field": k, "value": v["value"], "source": {"type": v.get("source") or "voice"},
              "status": v.get("status"), "hedged": bool(v.get("hedge"))}
        facts.append(row)
        for alias in _CANONICAL_ALIASES.get(k, []):
            facts.append({**row, "field": alias})
    given, family = ctx["facts"].get("name.given"), ctx["facts"].get("name.family")
    if given and family:
        facts.append({"field": "legal_name", "value": f"{given['value']} {family['value']}",
                     "source": {"type": given.get("source") or "voice"}, "status": given.get("status")})
    documents = [{"id": d["id"], "name": d.get("document_type"), "type": d.get("document_type"),
                 "extracted_text": json.dumps(d.get("extraction") or {})} for d in ctx["documents"]]
    tasks = [{"id": t["id"], "title": t["title"], "status": t["status"], "owner": t["agent"],
             "field": t.get("field")} for t in ctx["tasks"]]
    basis = ctx["facts"].get("eligibility_basis", {}).get("value")
    married = ctx["facts"].get("spouse.citizenship_status", {}).get("value") == "us_citizen"
    # Sent at both the top level and inside "case": the agents' own documented bundle shapes disagree on
    # where this belongs (paralegal's own test fixture has it as a get_case sibling; nothing we read put
    # it inside "case" at all), so cover both rather than guess wrong and reproduce the bug we just found.
    language = ctx.get("language", "es")
    return {"case": {"client_name": ctx["case"].get("first_name"), "stage": ctx["case"]["state"],
                     "eligibility_basis": "3_year" if basis == "3yr" else "5_year",
                     "married_to_us_citizen": married, "client_language": language},
            "client_language": language,
            "facts": facts, "documents": documents, "tasks": tasks,
            "deadlines": ctx.get("deadlines") or [], "derived": ctx.get("derived") or {}}


POLL_INTERVAL_S = 4
POLL_TIMEOUT_S = 90
_VALID_ITEM_TYPES = {"briefing", "task", "review_item", "gap", "gap_close", "memo", "deadline", "evidence",
                    "doc_checks", "review_note"}


def _fetch_json(headers: dict, url: str) -> dict:
    r = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _artifact_url(result: dict, title: str) -> str | None:
    for a in result.get("artifacts", []):
        if a["title"] == title:
            return a["url"]
    return None


def _findings_to_tasks(findings: list[dict]) -> list[dict]:
    """Generic translation for the docket_clerk/qa_reviewer engines' findings[] arrays -- not a full
    mapping of every field, just enough to get real findings into the case for review."""
    items = []
    for f in findings:
        title = f.get("message") or f.get("title") or f.get("detail") or f.get("code") or "finding"
        sev = (f.get("severity") or "").title()
        items.append({"type": "task", "payload": {"kind": "finding",
                      "title": f"[{sev}] {title}" if sev else title, "field": f.get("field")}})
    return items


def _parse_chat_items(chat_text: str) -> list[dict]:
    """Generic fenced ```json {"items": [...]}``` block anywhere in an agent's chatText -- the shape
    doc_paralegal's engine already returns, and the one a Gmail-MCP-equipped agent (doc_paralegal's
    inbox search, case_manager's escalation-sent note) is expected to use too, same as any other item
    it proposes. Unknown/malformed content yields no items rather than raising -- chatText is prose with
    an optional block in it, not a guaranteed contract."""
    m = re.search(r"```json\s*(.*?)\s*```", chat_text or "", re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    out = []
    for it in obj.get("items", []):
        if it.get("type") not in _VALID_ITEM_TYPES:
            continue
        payload = {k: v for k, v in it.items() if k != "type"}
        if "exhibit" in payload and payload["exhibit"] is not None:
            payload["exhibit"] = str(payload["exhibit"])
        out.append({"type": it["type"], "payload": payload})
    return out


def _translate(agent: str, result: dict, headers: dict, language: str) -> list[dict]:
    """Each Creao engine returns its own native shape (see the design doc). Map the parts we can into
    our proposal envelope's item list; anything not mapped here is simply not written back yet."""
    if agent == "doc_paralegal":
        return _parse_chat_items(result.get("chatText", ""))
    if agent == "docketing_clerk":
        url = _artifact_url(result, "docket.json")
        if not url:
            return []
        return _findings_to_tasks(_fetch_json(headers, url).get("findings", []))
    if agent == "qa_reviewer":
        url = _artifact_url(result, "qa_findings.json")
        if not url:
            return []
        return _findings_to_tasks(_fetch_json(headers, url).get("findings", []))
    if agent == "case_manager":
        out = _parse_chat_items(result.get("chatText", ""))  # e.g. an escalation-sent memo, if any
        url = _artifact_url(result, "question_queue.json")
        if url:
            qkey = f"question_{language}"
            queue = [{"kind": "ask", "field": q.get("field"), qkey: q.get("text"), "reason": q.get("why")}
                    for q in _fetch_json(headers, url).get("questions", [])]
            out.append({"type": "briefing", "payload": {"queue": queue}})
        return out
    return []


class CreaoBackend:
    """Calls each agent's own Creao app directly -- one (api_key, app_id) pair per agent, set as
    <AGENT>_API_KEY / <AGENT>_APP_ID (e.g. CASE_MANAGER_API_KEY, CASE_MANAGER_APP_ID). The case bundle
    is sent inline as `inputs.case_bundle`; the runner already has this data (same build_context() the
    skeleton backend uses), so the agent needs no live MCP/tool connection back to us for a read.

    POST {CREAO_BASE_URL}/api/v1/apps/<app_id>/runs, Authorization: Bearer <api_key>, body {"inputs":
    {...}}; returns a pending run id. Polled via GET .../runs/<id> until status leaves pending/running
    (confirmed live against all four agents, 2026-10-24). Only doc_paralegal returns its envelope-shaped
    output inline (a fenced JSON block in result.chatText); the other three return a summary inline and
    their real structured output as a downloadable artifact file -- _translate() fetches and maps those.
    """
    name = "creao"
    model = None

    def run(self, agent: str, ctx: dict, run_id: str, error: str | None = None) -> dict:
        prefix = agent.upper()
        key = os.environ.get(f"{prefix}_API_KEY")
        app_id = os.environ.get(f"{prefix}_APP_ID")
        if not key or not app_id:
            raise BackendError(f"Creao not configured for {agent} ({prefix}_API_KEY / {prefix}_APP_ID)")
        base = os.environ.get("CREAO_BASE_URL", "https://agent.creao.ai")
        headers = {"Authorization": f"Bearer {key}"}
        try:
            r = httpx.post(f"{base}/api/v1/apps/{app_id}/runs", headers=headers, timeout=30,
                           json={"inputs": {"case_id": ctx["case"]["id"], "trigger": "staff_round_done",
                                            "case_bundle": _to_case_bundle(ctx)}})
            r.raise_for_status()
            creao_run_id = r.json()["id"]
            deadline = time.time() + POLL_TIMEOUT_S
            result = None
            while time.time() < deadline:
                time.sleep(POLL_INTERVAL_S)
                rr = httpx.get(f"{base}/api/v1/apps/{app_id}/runs/{creao_run_id}", headers=headers, timeout=30)
                rr.raise_for_status()
                d = rr.json()
                if d["status"] not in ("pending", "running"):
                    result = d
                    break
        except httpx.HTTPError as e:
            # network blip, rate limit, transient 5xx, expired key, etc. -- surfaced to run_job() as a
            # BackendError so the job fails cleanly (Task + agent.run_failed event) instead of leaving
            # the job stuck in "running" forever with an uncaught exception.
            raise BackendError(f"Creao call failed for {agent}: {e}") from e
        if result is None:
            raise BackendError(f"Creao run {creao_run_id} ({agent}) timed out after {POLL_TIMEOUT_S}s")
        if result["status"] != "completed":
            raise BackendError(f"Creao run {creao_run_id} ({agent}) ended with status {result['status']}")
        try:
            items = _translate(agent, result["result"], headers, ctx.get("language", "es"))
        except httpx.HTTPError as e:
            raise BackendError(f"Creao artifact fetch failed for {agent}: {e}") from e
        return {"agent": agent, "run_id": run_id, "case_id": ctx["case"]["id"],
                "based_on_event_id": ctx.get("latest_event_id"), "items": items}


class FakeBackend:
    """Test helper: returns whatever `outputs` yields (used to prove AT19 / AT20)."""
    name = "fake"
    model = None

    def __init__(self, outputs):
        self.outputs = list(outputs)

    def run(self, agent: str, ctx: dict, run_id: str, error: str | None = None) -> dict:
        out = self.outputs.pop(0) if self.outputs else {}
        return out(agent, ctx, run_id) if callable(out) else out


def get_backend(name: str | None = None):
    name = name or settings.agent_backend
    if name == "anthropic" and settings.anthropic_api_key:
        return AnthropicBackend()
    if name == "creao":
        return CreaoBackend()
    return SkeletonBackend()
