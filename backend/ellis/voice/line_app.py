"""Ellis liaison as a Cartesia Line agent (deploy with the Line CLI; Ink 2 STT + Sonic TTS run on Cartesia).

    cd backend && python -m ellis.voice.line_app   # local (pip install -e ".[line]"); `cartesia chat 8000`

Start calls with metadata {"case_id": "<case>"}: it is baked into every tool (constant_value), so the model can
never name another case. Tools call the Case API (/tools/*) with Authorization: Bearer $ELLIS_TOOL_SECRET.

Brains:
- ELLIS_LINE_BRAIN=scripted (default): the deterministic liaison turn engine (same as the web gateway).
- ELLIS_LINE_BRAIN=llm: a Claude LlmAgent with the liaison prompt and HTTP tools, wrapped in the in-loop
  keyword guard (layer 4) so a stop-list turn never reaches the model and plays the locked stop script.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from line.agent import TurnEnv
from line.events import (
    AgentEndCall, AgentSendText, CallEnded, CallStarted, CustomHistoryEntry, InputEvent, UserTurnEnded,
)
from line.voice_agent_app import AgentEnv, CallRequest, VoiceAgentApp

from ..services import keywords, languages
from .client import HttpClient
from .liaison import Liaison, script

API = os.environ.get("ELLIS_API_URL", "http://localhost:8000")
SECRET = os.environ.get("ELLIS_TOOL_SECRET", "dev-tool-secret")
PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "liaison.md")


def _text(event: UserTurnEnded) -> str:
    return " ".join(getattr(c, "content", "") for c in event.content).strip()


class ScriptedLineAgent:
    """Line Agent protocol wrapper around the deterministic liaison."""

    def __init__(self, case_id: str):
        self.liaison = Liaison(HttpClient(API, SECRET, case_id), channel="line")

    async def process(self, env: TurnEnv, event: InputEvent):
        if isinstance(event, CallStarted):
            lines = await asyncio.to_thread(self.liaison.start)
        elif isinstance(event, UserTurnEnded):
            # Line does not report the interrupted word (open question 4): the liaison's open read-back field
            # receives the correction, which is the documented fallback.
            lines = await asyncio.to_thread(self.liaison.handle, _text(event), None, None)
        elif isinstance(event, CallEnded):
            await asyncio.to_thread(self.liaison.c.session_end)
            return
        else:
            return
        for ln in lines:
            yield AgentSendText(text=ln.text, interruptible=not ln.locked)
            if ln.end_call:
                yield AgentEndCall()


class KeywordGuard:
    """Layer 4 in the Line handler: runs on every final transcript before the LLM."""

    def __init__(self, inner, client: HttpClient):
        self.inner = inner
        self.client = client
        self.stopped_categories: set[str] = set()

    async def process(self, env: TurnEnv, event: InputEvent):
        if isinstance(event, UserTurnEnded):
            text = _text(event)
            cat = keywords.stop_hit(text)
            if cat:
                await asyncio.to_thread(self.client.applicant_turn, text)  # stored as [STOP:<category>] only
                # replace the turn in the LLM's history; it must never see the words
                try:
                    self.inner.history.update([CustomHistoryEntry(
                        content="[applicant disclosed a stop-list topic; do not refer to it]")], start=event)
                except Exception:  # noqa: BLE001 - fallback: fresh context seeded from the briefing (open q. 3)
                    pass
                first = cat not in self.stopped_categories
                self.stopped_categories.add(cat)
                line = script("stop") if first else script("stop_repeat")
                yield AgentSendText(text=line.text, interruptible=not line.locked)
                return
            if keywords.has_sensitive_number(text):
                await asyncio.to_thread(self.client.applicant_turn, text)
                await asyncio.to_thread(self.client.request_secure_entry, "a_number")
                line = script("secure_entry_repeat")
                yield AgentSendText(text=line.text, interruptible=False)
                return
        async for out in self.inner.process(env, event):
            yield out


def _llm_agent(case_id: str, clinic_name: str, lang: str = "en"):
    from line.llm_agent import LlmAgent, LlmConfig, end_call, http_server_tool

    auth = {"Authorization": f"Bearer {SECRET}", "X-Ellis-Case": case_id}

    def tool(name, desc, props=None, required=None):
        return http_server_tool(name=name, description=desc, url=f"{API}/tools/{name}", method="POST",
                                request_body_schema={"type": "object", "properties": props or {},
                                                     "required": required or []},
                                auth=auth, timeout=5.0, is_background=False)

    tools = [
        tool("get_briefing", "Read the latest briefing. Call at session start and after every completed answer."),
        tool("record_fact", "Record a fact the applicant stated, in the same turn.",
             {"field": {"type": "string"}, "value": {}, "hedge": {"type": "boolean"},
              "utterance_text": {"type": "string"}}, ["field", "value"]),
        tool("read_back", "Start a one-field read-back. Speak exactly the returned sentence_es.",
             {"field": {"type": "string"}, "read_value": {"type": "string", "enum": ["applicant", "document"]}},
             ["field"]),
        tool("flag_for_review", "Flag something for the clinic reviewer (never explain consequences).",
             {"category": {"type": "string"}, "field": {"type": "string"}}, ["category"]),
        tool("stop_script", "Stop-list topic: call immediately and say nothing else this turn.",
             {"category": {"type": "string", "enum": ["arrest", "removal", "citizenship_claim", "fraud", "danger"]}},
             ["category"]),
        tool("request_secure_entry", "Open the on-screen secure entry for a sensitive number.",
             {"field": {"type": "string"}}, ["field"]),
        tool("request_upload", "Open the upload sheet on the applicant's phone.",
             {"document_type": {"type": "string"}}, ["document_type"]),
        end_call,
    ]
    prompt = (PROMPT.read_text(encoding="utf-8").replace("{clinic_name}", clinic_name)
              .replace("{language}", languages.name(lang)))
    disclosure = script("disclosure", lang=lang, clinic_name=clinic_name).text
    return LlmAgent(model=os.environ.get("ELLIS_LINE_MODEL", "anthropic/claude-haiku-5-5"),
                    api_key=os.environ.get("ANTHROPIC_API_KEY"), tools=tools,
                    config=LlmConfig(system_prompt=prompt, introduction=disclosure))


async def get_agent(env: AgentEnv, call_request: CallRequest):
    case_id = (call_request.metadata or {}).get("case_id")
    if not case_id:
        raise ValueError("call metadata must include case_id")
    client = HttpClient(API, SECRET, case_id)
    if os.environ.get("ELLIS_LINE_BRAIN", "scripted") == "llm" and os.environ.get("ANTHROPIC_API_KEY"):
        cfg = await asyncio.to_thread(client.session_start, "line")
        return KeywordGuard(_llm_agent(case_id, cfg.get("clinic_name", "your clinic"), cfg.get("language", "en")), client)
    return ScriptedLineAgent(case_id)


app = VoiceAgentApp(get_agent=get_agent)

if __name__ == "__main__":  # pragma: no cover
    app.run()
