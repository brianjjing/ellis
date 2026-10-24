"""Claude-driven liaison: the model decides what to ask and when, inside the same safety rails as the
scripted liaison (ellis/voice/liaison.py). The model can only act through tools that call the Case API, so
recording, validation, flagging, date math, and the stop-list stay exactly as strict as the deterministic
engine -- Claude gets freedom over conversation flow and phrasing, never over facts.

Same two-layer safety as the Line "llm" brain in line_app.py:
  1. self.c.applicant_turn(text) runs the keyword backstop server-side, same as the scripted liaison, BEFORE
     the model ever sees the transcript. A stop-list hit or a sensitive number never reaches Claude.
  2. Inside the loop, the model can only change state by calling a tool; every tool is a thin wrapper over
     the same case_service functions the scripted liaison uses.

Public contract matches Liaison (start/handle/close/silence -> list[Say]), so routes/voice.py can use either
engine without knowing which one is driving the conversation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..config import settings
from .liaison import Say, script

log = logging.getLogger("ellis.llm_liaison")
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "liaison.md"
MAX_TOOL_ROUNDS = 6

TOOLS = [
    {"name": "get_briefing", "description": "Read the latest briefing: required fields still missing, "
     "suggested next questions, open flags, gaps, progress by section. Call at session start and after "
     "every completed answer so you always know what's genuinely still needed.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "record_fact", "description": "Record a fact the applicant stated, in the same turn you heard "
     "it. Never say a fact is saved until this tool returns saved:true.",
     "input_schema": {"type": "object", "properties": {
         "field": {"type": "string", "description": "field key from get_briefing"}, "value": {},
         "hedge": {"type": "boolean", "description": "true if the applicant sounded unsure or was guessing"}},
         "required": ["field", "value"]}},
    {"name": "read_back", "description": "Start a one-field read-back so the applicant can confirm it. Speak "
     "exactly the sentence this tool returns; never combine two fields in one read-back.",
     "input_schema": {"type": "object", "properties": {
         "field": {"type": "string"},
         "read_value": {"type": "string", "enum": ["applicant", "document"],
                       "description": "which value to read back when both exist"}},
         "required": ["field"]}},
    {"name": "flag_for_review", "description": "Flag something for the clinic reviewer. Never explain "
     "consequences to the applicant -- just say the neutral flag line and move on.",
     "input_schema": {"type": "object", "properties": {
         "category": {"type": "string"}, "field": {"type": "string"}}, "required": ["category"]}},
    {"name": "stop_script", "description": "The applicant said something about arrest, police custody, "
     "deportation, removal, claiming US citizenship, voting, false documents, or harming anyone. Call this "
     "immediately and say nothing else this turn -- the fixed stop message is sent for you.",
     "input_schema": {"type": "object", "properties": {
         "category": {"type": "string", "enum": ["arrest", "removal", "citizenship_claim", "fraud", "danger"]}},
         "required": ["category"]}},
    {"name": "request_secure_entry", "description": "Open the on-screen secure entry for a sensitive number "
     "(A-number, SSN, case number). Never ask the applicant to say a sensitive number aloud.",
     "input_schema": {"type": "object", "properties": {"field": {"type": "string"}}, "required": ["field"]}},
    {"name": "request_upload", "description": "Open the document upload sheet for the applicant's phone.",
     "input_schema": {"type": "object", "properties": {"document_type": {"type": "string"}},
                      "required": ["document_type"]}},
    {"name": "end_call", "description": "End the session for today: everything needed for this session is "
     "done, the applicant wants to stop, or they declined consent.",
     "input_schema": {"type": "object", "properties": {}}},
]


class LlmLiaison:
    """Drop-in replacement for Liaison when ANTHROPIC_API_KEY is set."""

    def __init__(self, client, language: str = "en", model: str | None = None, channel: str = "voice"):
        self.c = client
        self.language = language
        self.channel = channel
        self.model = model or settings.conversation_model
        self.ended = False
        self.cfg: dict[str, Any] = {}
        self.history: list[dict] = []
        self._system = ""
        self._anthropic = None

    def _client_(self):
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._anthropic

    # ------------------------------------------------------------ lifecycle

    def start(self) -> list[Say]:
        self.cfg = self.c.session_start(self.channel)
        clinic_name = self.cfg.get("clinic_name") or ("su clínica" if self.language == "es" else "your clinic")
        self._system = (PROMPT_PATH.read_text(encoding="utf-8")
                        .replace("{clinic_name}", clinic_name)
                        .replace("{language}", "Spanish" if self.language == "es" else "English"))
        if not self.cfg.get("consent_given"):
            disclosure = script("disclosure", lang=self.language, clinic_name=clinic_name)
            self.history.append({"role": "assistant", "content": disclosure.text})
            return self._said([disclosure])
        # resuming: seed real conversational memory from what was actually said, not just the facts
        # briefing, so the model picks the thread back up instead of feeling like a fresh form.
        for speaker, text in self.c.recent_transcript():
            self.history.append({"role": "assistant" if speaker == "liaison" else "user", "content": text})
        if self.history and self.history[0]["role"] == "assistant":
            self.history.insert(0, {"role": "user", "content": "[session started]"})  # API requires user first
        nudge = (f"[system] Resuming a previous session. Greet "
                f"{self.cfg.get('first_name') or 'the applicant'} briefly and continue naturally from where "
                "the conversation above left off -- call get_briefing for what's still needed.")
        return self._said(self._turn_model(nudge, None, False))

    def _said(self, lines: list[Say]) -> list[Say]:
        for ln in lines:
            try:
                self.c.liaison_said(ln.text, ln.locked)
            except Exception:  # noqa: BLE001 - captions are best-effort
                log.exception("liaison_said failed")
        return lines

    # ------------------------------------------------------------ turns

    def handle(self, text: str, interrupted_field: str | None = None,
               interrupted_at_word: str | None = None, turn_uncertain: bool = False) -> list[Say]:
        if self.ended:
            return []
        text = (text or "").strip()
        if not text:
            return []
        # layer 4, server-side, before the model ever sees the transcript -- same check the scripted
        # liaison runs, so a stop-list word or a spoken sensitive number never reaches Claude either way.
        t = self.c.applicant_turn(text)
        if t.get("stop"):
            self.c.stop_spoken()
            return self._said([script("stop", lang=self.language)])
        if t.get("redacted"):
            self.c.request_secure_entry("a_number")
            return self._said([script("secure_entry_repeat", lang=self.language)])
        return self._said(self._turn_model(text, t.get("utterance_id"), turn_uncertain))

    def _turn_model(self, text: str, uid: str | None, hedge_hint: bool) -> list[Say]:
        user_content = text if not hedge_hint else f"{text}\n[the speech model flagged this as hesitant/unsure]"
        self.history.append({"role": "user", "content": user_content})
        end_call = False
        texts: list[str] = []
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                resp = self._client_().messages.create(model=self.model, max_tokens=600, system=self._system,
                                                        tools=TOOLS, messages=self.history)
            except Exception:  # noqa: BLE001
                log.exception("conversation model call failed")
                return [script("tool_failure", lang=self.language)]
            assistant_blocks = [b.model_dump() for b in resp.content]
            self.history.append({"role": "assistant", "content": assistant_blocks})
            texts += [b["text"] for b in assistant_blocks if b.get("type") == "text" and b.get("text")]
            tool_uses = [b for b in assistant_blocks if b.get("type") == "tool_use"]
            if not tool_uses:
                break
            results = []
            stopped = False
            for call in tool_uses:
                name, args, call_id = call["name"], call.get("input") or {}, call["id"]
                if name == "end_call":
                    end_call = True
                    results.append({"type": "tool_result", "tool_use_id": call_id, "content": "ok"})
                    continue
                if name == "stop_script":
                    out = self._call_tool(name, args, uid, text)
                    results.append({"type": "tool_result", "tool_use_id": call_id, "content": "ok"})
                    stopped = True
                    continue
                out = self._call_tool(name, args, uid, text)
                results.append({"type": "tool_result", "tool_use_id": call_id,
                                "content": json.dumps(_jsonable(out))})
            self.history.append({"role": "user", "content": results})
            if stopped:
                self.c.stop_spoken()
                return [script("stop", lang=self.language)]
            if resp.stop_reason != "tool_use":
                break
        line = Say(" ".join(texts).strip() or script("tool_failure", lang=self.language).text,
                  kind="llm", end_call=end_call)
        if end_call:
            self.ended = True
        return [line]

    def _call_tool(self, name: str, args: dict, uid: str | None, text: str) -> Any:
        try:
            if name == "get_briefing":
                return self.c.get_briefing()
            if name == "record_fact":
                return self.c.record_fact(args["field"], args.get("value"), hedge=bool(args.get("hedge")),
                                          utterance_id=uid, utterance_text=text)
            if name == "read_back":
                return self.c.read_back(args["field"], args.get("read_value"), lang=self.language)
            if name == "flag_for_review":
                return self.c.flag_for_review(args["category"], args.get("field"))
            if name == "stop_script":
                return self.c.stop_script(args["category"])
            if name == "request_secure_entry":
                self.c.request_secure_entry(args["field"])
                return {"ok": True}
            if name == "request_upload":
                self.c.request_upload(args["document_type"])
                return {"ok": True}
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return {"error": str(e)}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------ session close / silence

    def close(self, all_done: bool = False) -> list[Say]:
        if self.ended:
            return []
        b = self.c.get_briefing()
        close = b.get("session_close") or {}
        nudge = ("[system] The applicant is ending the session for today. Sections finished: {}. "
                "Still needed next time: {}. Say a brief, warm goodbye in {} summarizing this naturally -- "
                "do not read the lists verbatim -- then call end_call.").format(
            close.get("sections_done") or "the basics", close.get("next_items") or "nothing else right now",
            "Spanish" if self.language == "es" else "English")
        lines = self._turn_model(nudge, None, False)
        self.ended = True
        return self._said(lines)

    def silence(self, seconds: float) -> list[Say]:
        if self.ended:
            return []
        nudge = (f"[system] The applicant has been silent for {int(seconds)} seconds after your last question. "
                "Gently check in or offer to continue another time; do not repeat the exact same question "
                "word for word.")
        return self._said(self._turn_model(nudge, None, False))


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
