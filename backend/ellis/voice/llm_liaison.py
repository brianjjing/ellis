"""Claude-driven applicant assistant: one agent that helps with whatever the applicant asks for -- the N-400,
documents, interview practice, reminders, their own answers, their settings -- with no scripted route through
it. Only the legal lines are fixed (disclosure, stop, secure entry).

The payload follows the applicant. Every model call carries a "live case data" block rebuilt from the database
for the current focus (views.agent_context); the model moves the focus with set_focus, so the next call
already carries the detail for the new task (N-400 questions still needed, practice questions, all reminders,
their answers, setting options). The model can only state what that block or a tool result says.

Safety, unchanged from the scripted liaison (ellis/voice/liaison.py):
  1. self.c.applicant_turn(text) runs the keyword backstop server-side BEFORE the model sees the transcript.
     A stop-list hit or a sensitive number never reaches Claude.
  2. The model changes state only through tools that wrap case_service functions.
  3. New: anything better left to a person -- a settings change, a question for the clinic -- goes through a
     permission card the applicant taps. The model can ask; only the applicant's tap (permission()) applies it.

Public contract matches Liaison (start/handle/close/silence -> list[Say]), plus permission(id, allow).
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from ..services.case_service import APPLICANT_SETTINGS, SETTING_NAMES
from ..services.flags import STOP_NOW, category as flag_category
from ..services.views import FOCI
from .liaison import Say, script

log = logging.getLogger("ellis.llm_liaison")
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "liaison.md"
MAX_TOOL_ROUNDS = 6
PAGES = ["/form", "/interview", "/reminders", "/profile", "/review"]
# what the model gets in place of a stop-list turn, live or on resume: never the topic itself
STOP_NOTE = ("[the applicant raised a topic only a licensed professional can review; the fixed stop message was "
             "played. Don't refer to it.]")

TOOLS = [
    {"name": "set_focus", "description": "Set what the applicant is working on now. Call it whenever their goal "
     "changes, and in the opening with your suggestion. It updates the next-step bar on their screen and what "
     "the live case data block carries on your next call.",
     "input_schema": {"type": "object", "properties": {
         "task": {"type": "string", "enum": list(FOCI)},
         "next_step": {"type": "string", "description": "the step as the applicant sees it in the bar, under 8 "
                       "words, in reply_language, e.g. 'Answer the questions about your trips'"},
         "section": {"type": "string", "description": "for task n400: the part's key from n400.parts, when the "
                     "applicant wants a particular part; still_needed then leads with it"},
         "link": {"type": "string", "enum": PAGES, "description": "optional page button in the bar"},
         "upload": {"type": "string", "description": "optional document_type for an upload button in the bar"}},
         "required": ["task", "next_step"]}},
    {"name": "record_fact", "description": "Record a fact the applicant stated, in the same turn you heard "
     "it. Never say a fact is saved until this tool returns saved:true.",
     "input_schema": {"type": "object", "properties": {
         "field": {"type": "string", "description": "field key from still_needed"}, "value": {},
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
    {"name": "request_upload", "description": "Open the document upload sheet on the applicant's screen.",
     "input_schema": {"type": "object", "properties": {"document_type": {"type": "string"}},
                      "required": ["document_type"]}},
    {"name": "request_biographics", "description": "Open the on-screen pickers for height, weight, eye and hair "
     "color, ethnicity and race (still_needed item request_biographics).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "change_setting", "description": "Ask to change one of the applicant's settings. This does NOT "
     "change it: it shows an Allow / Don't allow card, and a [system] message tells you what they chose. "
     "Allowed values: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in APPLICANT_SETTINGS.items()),
     "input_schema": {"type": "object", "properties": {
         "setting": {"type": "string", "enum": list(APPLICANT_SETTINGS)}, "value": {"type": "string"}},
         "required": ["setting", "value"]}},
    {"name": "ask_clinic", "description": "Offer to send the applicant's question to a person at their clinic. "
     "Shows an Allow / Don't allow card; nothing is sent until they tap Allow.",
     "input_schema": {"type": "object", "properties": {
         "question": {"type": "string", "description": "the question in the applicant's own words, 1-2 sentences"}},
         "required": ["question"]}},
    {"name": "end_call", "description": "End the session for today: the applicant wants to stop, or they "
     "declined consent.",
     "input_schema": {"type": "object", "properties": {}}},
]


class LlmLiaison:
    """The applicant's conversation engine (requires ANTHROPIC_API_KEY)."""

    def __init__(self, client, language: str = "en", model: str | None = None, channel: str = "voice"):
        self.c = client
        self.language = language
        self.channel = channel
        self.model = model or settings.conversation_model
        self.ended = False
        self.cfg: dict[str, Any] = {}
        self.history: list[dict] = []
        self.focus: dict[str, Any] = {"task": "general"}
        self.pending: dict[str, dict] = {}  # permission id -> what the applicant is being asked to allow
        self.flags: list[dict] = []  # flags raised this turn; they ride on Ellis's reply as a margin note
        self._system = ""
        self._anthropic = None

    def _client_(self):
        if self._anthropic is None:
            import anthropic
            self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return self._anthropic

    # ------------------------------------------------------------ lifecycle

    def start(self, disclosure_shown: bool = False) -> list[Say]:
        self.cfg = self.c.session_start(self.channel)
        clinic_name = self.cfg.get("clinic_name") or ("su clínica" if self.language == "es" else "your clinic")
        self._system = PROMPT_PATH.read_text(encoding="utf-8").replace("{clinic_name}", clinic_name)
        if not self.cfg.get("consent_given"):
            disclosure = script("disclosure", lang=self.language, clinic_name=clinic_name)
            self.history.append({"role": "user", "content": "[session started]"})  # API requires user first
            self.history.append({"role": "assistant", "content": disclosure.text})
            # back on a chat whose disclosure is still on screen, unanswered: wait for the reply, don't repeat it
            return [] if disclosure_shown else self._said([disclosure])
        # resuming: seed real conversational memory from what was actually said, so the model picks the
        # thread back up instead of feeling like a fresh form.
        past = self.c.recent_transcript()
        for speaker, text, _ in past:
            if text.startswith("[STOP:"):  # a stored stop turn: the model gets the live note, never the category
                text = STOP_NOTE
            self._append("assistant" if speaker == "liaison" else "user", text)
        if self.history and self.history[0]["role"] == "assistant":
            self.history.insert(0, {"role": "user", "content": "[session started]"})
        meta = self._suggest()
        asked = last_question(past)
        where = "" if asked is None else (f' Before the break you asked: "{asked[0]}" -- ' + (
            "they answered it." if asked[1] else "they never answered it."))
        lines = self._turn_model(f"[system] {self.cfg.get('first_name') or 'The applicant'} just opened the chat "
                                 f"(returning; consent was given before).{where} Give the opening.", None)
        lines[0].meta = {**meta, **lines[0].meta}
        return self._said(lines)

    def _suggest(self) -> dict[str, Any]:
        """Opening: the focus becomes the suggested next step, so the next-step bar on screen and what Ellis
        recommends are the same thing. The applicant still chooses what to do."""
        try:
            self.focus = dict(self.c.agent_context(self.focus)["suggested_next_step"])
        except Exception:  # noqa: BLE001 - no suggestion beats a crashed opening
            log.exception("suggested_next failed")
        return {"focus": self.focus}

    def _append(self, role: str, content: Any) -> None:
        # the API wants alternating roles; merge consecutive plain-text turns (e.g. two lines in a row)
        if self.history and self.history[-1]["role"] == role and isinstance(content, str) \
                and isinstance(self.history[-1]["content"], str):
            self.history[-1]["content"] += "\n" + content
        else:
            self.history.append({"role": role, "content": content})

    def _said(self, lines: list[Say]) -> list[Say]:
        for ln in lines:
            try:
                self.c.liaison_said(ln.text, ln.locked, {"kind": ln.kind})  # kind: so a resume can skip check-ins
            except Exception:  # noqa: BLE001 - captions are best-effort
                log.exception("liaison_said failed")
        return lines

    def _payload(self) -> list[dict]:
        """System prompt (cached) + the live case data block for the current focus (rebuilt every call)."""
        try:
            ctx = self.c.agent_context(self.focus)
        except Exception:  # noqa: BLE001
            log.exception("agent_context failed")
            ctx = {"error": "case data is unavailable right now: don't state any case facts, dates or status"}
        ctx["focus"] = self.focus
        ctx["waiting_for_permission"] = [p["title"] for p in self.pending.values()]
        return [{"type": "text", "text": self._system, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": "## Live case data (rebuilt for this call; the only source of truth)\n"
                 + json.dumps(_jsonable(ctx), ensure_ascii=False)}]

    # ------------------------------------------------------------ turns

    def handle(self, text: str, interrupted_field: str | None = None, interrupted_at_word: str | None = None,
               turn_uncertain: bool = False, unheard: bool = False) -> list[Say]:
        if self.ended:
            return []
        text = (text or "").strip()
        if not text:
            return []
        # layer 4, server-side, before the model ever sees the transcript: a stop-list word or a spoken
        # sensitive number never reaches Claude.
        t = self.c.applicant_turn(text)
        if t.get("stop"):
            self.c.stop_spoken()
            self._append("user", STOP_NOTE)
            self._append("assistant", script("stop", lang=self.language).text)
            return self._said([script("stop", lang=self.language)])
        if t.get("redacted"):
            self.c.request_secure_entry("a_number")
            line = script("secure_entry_repeat", lang=self.language)
            # the rest of the turn still counts: the model sees it with the number taken out
            self._append("user", f"{t.get('text', '')}\n[a sensitive number was taken out before you saw this; "
                         "the secure entry was opened for it]")
            self._append("assistant", line.text)
            return self._said([line])
        self.flags = list(t.get("flags") or [])  # keyword backstop (layer 4)
        # what they didn't hear: a bare "yes" must never answer a question that didn't reach them
        hints = []
        if unheard:
            hints.append("they said this before your last reply reached them: they never heard it")
        elif interrupted_at_word:
            hints.append(f'they cut you off at "{interrupted_at_word}": they never heard the rest of your last reply')
        if turn_uncertain:
            hints.append("the speech model flagged this as hesitant/unsure")
        return self._said(self._turn_model(text, t.get("utterance_id"), "; ".join(hints)))

    def permission(self, pid: str, allow: bool) -> list[Say]:
        """The applicant tapped Allow / Don't allow on a card. The only path that applies what the model asked."""
        p = self.pending.pop(pid, None)
        if self.ended or p is None:
            return []
        if not allow:
            note = (f"[system] The applicant tapped Don't allow on: {p['title']}. Nothing was changed or sent. "
                    "Acknowledge in a few words and carry on.")
        else:
            try:
                if p["kind"] == "setting":
                    out = self.c.set_setting(**p["args"])
                    self.cfg.update(self.c.call_config())  # new language / voice speed apply from the next line
                    self.language = self.cfg.get("language", self.language)
                else:
                    out = self.c.ask_clinic(p["args"]["question"])
                note = (f"[system] The applicant tapped Allow on: {p['title']}. Done: {json.dumps(_jsonable(out))}. "
                        "Confirm it briefly and carry on.")
            except Exception as e:  # noqa: BLE001
                log.exception("permission %s failed", p["kind"])
                note = (f"[system] The applicant allowed {p['title']}, but it didn't go through "
                        f"({getattr(e, 'message', e)}). Say so plainly; they can try again or ask their clinic.")
        return self._said(self._turn_model(note, None))

    def _turn_model(self, text: str, uid: str | None, hint: str = "") -> list[Say]:
        self._append("user", f"{text}\n[{hint}]" if hint else text)
        end_call = False
        texts: list[str] = []
        meta: dict[str, Any] = {}
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                resp = self._client_().messages.create(model=self.model, max_tokens=800, system=self._payload(),
                                                        tools=TOOLS, messages=self.history)
            except Exception:  # noqa: BLE001
                log.exception("conversation model call failed")
                return [script("tool_failure", lang=self.language)]
            blocks = [b.model_dump(exclude_none=True) for b in resp.content]
            self.history.append({"role": "assistant", "content": blocks})
            texts += [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
            tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not tool_uses:
                break
            results = []
            stopped = False
            for call in tool_uses:
                name, args = call["name"], call.get("input") or {}
                if name == "end_call":
                    end_call = True
                    out: Any = "ok"
                elif name == "stop_script":
                    self._call_tool(name, args, uid, text, meta)
                    stopped, out = True, "ok"
                else:
                    out = self._call_tool(name, args, uid, text, meta)
                results.append({"type": "tool_result", "tool_use_id": call["id"],
                                "content": out if isinstance(out, str) else json.dumps(_jsonable(out))})
            self.history.append({"role": "user", "content": results})
            if stopped:
                self.c.stop_spoken()
                self._append("assistant", script("stop", lang=self.language).text)
                return [script("stop", lang=self.language)]
            if resp.stop_reason != "tool_use":
                break
        if self.history[-1]["role"] == "user":  # ended on tool results: close the turn so roles alternate
            self.history.append({"role": "assistant", "content": " ".join(texts) or "(no reply)"})
        rb = meta.pop("readback_field", None)
        notes = self._flag_notes()
        if notes:
            meta["flags"] = notes
        line = Say(" ".join(texts).strip() or script("tool_failure", lang=self.language).text,
                  kind="readback" if rb else "llm", field=rb, end_call=end_call, meta=meta)
        if end_call:
            self.ended = True
        return [line]

    def _flag_notes(self) -> list[dict]:
        """What the applicant sees beside Ellis's reply: each item this turn sent to the clinic, once. Stop-list
        items have their own card; conflicts between documents are settled by read-back, not shown."""
        out, seen = [], set()
        for f in self.flags:
            if f.get("speed") == STOP_NOW or f.get("category") in ("date_conflict", "document_conflict",
                                                                   "document_owner") or f.get("id") in seen | {None}:
                continue
            seen.add(f["id"])
            label = f.get("label_es") or flag_category(f.get("category", "")).get(f"label_{self.language}")
            if label:
                out.append({"id": f["id"], "label": label})
        self.flags = []
        return out

    def _ask(self, kind: str, title: str, detail: str | None, args: dict, meta: dict) -> dict:
        pid = uuid.uuid4().hex[:8]
        self.pending[pid] = {"kind": kind, "title": title, "args": args}
        meta.setdefault("permissions", []).append({"id": pid, "kind": kind, "title": title, "detail": detail})
        return {"status": "card_shown", "note": "Nothing has happened yet. Tell them to tap Allow if they want "
                "it; never say it's done until a [system] message says they allowed it."}

    def _call_tool(self, name: str, args: dict, uid: str | None, text: str, meta: dict) -> Any:
        try:
            if name == "set_focus":
                if args.get("task") not in FOCI:
                    return {"error": f"task must be one of {list(FOCI)}"}
                self.focus = {k: args[k] for k in ("task", "next_step", "section", "link", "upload") if args.get(k)}
                if self.focus.get("link") not in PAGES:
                    self.focus.pop("link", None)
                meta["focus"] = self.focus
                return {"ok": True, "note": "the next call's live case data carries this focus"}
            if name == "record_fact":
                out = self.c.record_fact(args["field"], args.get("value"), hedge=bool(args.get("hedge")),
                                         utterance_id=uid, utterance_text=text)
                self.flags += out.get("flags") or []
                if args["field"] == "consent" and out.get("saved"):
                    self.cfg["consent_given"] = args.get("value") is True
                    if self.cfg["consent_given"]:
                        meta.update(self._suggest())
                return out
            if name == "read_back":
                out = self.c.read_back(args["field"], args.get("read_value"), lang=self.language)
                if not out.get("error"):
                    meta["readback_field"] = args["field"]
                return out
            if name == "flag_for_review":
                out = self.c.flag_for_review(args["category"], args.get("field"))
                self.flags.append({"id": out.get("flag_id"), "speed": out.get("speed"), "category": args["category"]})
                return out
            if name == "stop_script":
                return self.c.stop_script(args["category"])
            if name == "request_secure_entry":
                self.c.request_secure_entry(args["field"])
                return {"ok": True}
            if name == "request_upload":
                self.c.request_upload(args["document_type"])
                return {"ok": True}
            if name == "request_biographics":
                self.c.request_biographics()
                return {"ok": True}
            if name == "change_setting":
                key, value = args.get("setting"), args.get("value")
                if value not in APPLICANT_SETTINGS.get(key, {}):
                    return {"error": f"allowed values for {key}: {list(APPLICANT_SETTINGS.get(key, {}))}"}
                names, cur = APPLICANT_SETTINGS[key], self.c.call_config()["settings"][key]
                if cur == value:
                    return {"error": f"{key} is already {value}"}
                return self._ask("setting", f"{SETTING_NAMES[key]}: {names.get(cur, cur)} → {names[value]}", None,
                                 {"setting": key, "value": value}, meta)
            if name == "ask_clinic":
                q = " ".join(str(args.get("question") or "").split())
                if not q:
                    return {"error": "question is empty"}
                return self._ask("ask_clinic", f"Send your question to {self.cfg.get('clinic_name') or 'your clinic'}",
                                 q, {"question": q}, meta)
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", name)
            return {"error": str(e)}
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------ session close / silence

    def close(self, all_done: bool = False) -> list[Say]:
        if self.ended:
            return []
        lines = self._turn_model("[system] The applicant is ending the session for today. Say a brief, warm "
                                 "goodbye: what got done today and what's left, from the live case data, without "
                                 "reading lists. Everything is saved. Then call end_call.", None)
        self.ended = True
        return self._said(lines)

    def silence(self, seconds: float, last: bool = False) -> list[Say]:
        if self.ended:
            return []
        nudge = (f"[system] The applicant has been quiet for {int(seconds)} seconds. " + (
            "This is the last check-in: say in one short sentence that everything is saved and they can pick this "
            "up any time." if last else "Gently check in, in a few words; don't repeat your last question word "
            "for word, and don't say \"take your time\" if you said it already."))
        lines = self._turn_model(nudge, None)
        for ln in lines:
            ln.kind = "checkin"
        return self._said(lines)


def last_question(past: list[tuple[str, str, str | None]]) -> tuple[str, bool] | None:
    """The last thing Ellis asked before the break (check-ins and the disclosure aside), and whether the
    applicant replied after it. ponytail: "a question" = the line has a "?"; good enough for one-question turns."""
    for i in range(len(past) - 1, -1, -1):
        speaker, text, kind = past[i]
        if speaker == "liaison" and "?" in text and kind not in ("checkin", "disclosure"):
            return text, any(s != "liaison" for s, _, _ in past[i + 1:])
    return None


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)
