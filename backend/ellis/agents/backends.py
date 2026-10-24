"""Agent backends. All return a proposal envelope (dict) for the same context.

- skeleton:  deterministic Python (no model, no credits) — the default until keys/agents exist
- anthropic: prompts/<agent>.md + context → Claude → JSON envelope
- creao:     POST /v1/runs to a saved Creao agent; results arrive at /webhooks/creao (deduped by run id)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


class CreaoBackend:
    """Dispatch to a saved Creao agent. The agent reads the case through our MCP tools (scoped by role token)
    and posts its envelope to our webhook; the webhook handler applies it through the same validation path.

    Config: CREAO_API_KEY (cr_sk_…), CREAO_BASE_URL, CREAO_AGENT_<AGENT>=agent id, ELLIS_PUBLIC_API_URL.
    TODO(open-question-7): confirm the /v1/runs request/response fields against Creao's current API.
    """
    name = "creao"
    model = None
    asynchronous = True

    def dispatch(self, agent: str, case_id: str, reason: str, run_id: str) -> dict:
        key = os.environ.get("CREAO_API_KEY")
        agent_id = os.environ.get(f"CREAO_AGENT_{agent.upper()}")
        if not key or not agent_id:
            raise BackendError("Creao is not configured (CREAO_API_KEY / CREAO_AGENT_<AGENT>)")
        base = os.environ.get("CREAO_BASE_URL", "https://api.creao.ai")
        hook = os.environ.get("ELLIS_PUBLIC_API_URL", "http://localhost:8000") + "/webhooks/creao"
        r = httpx.post(f"{base}/v1/runs", headers={"Authorization": f"Bearer {key}"}, timeout=10, json={
            "agent_id": agent_id, "input": {"case_id": case_id, "reason": reason, "run_id": run_id},
            "webhook_url": hook})
        r.raise_for_status()
        return r.json()

    def run(self, agent: str, ctx: dict, run_id: str, error: str | None = None) -> dict:  # pragma: no cover
        raise BackendError("Creao runs are asynchronous; use dispatch()")


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
