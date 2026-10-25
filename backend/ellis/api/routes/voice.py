"""Applicant voice session: WS /api/a/voice.

Browser → server:  binary PCM16 mono 16 kHz mic frames (silence unless the talk button is held), or JSON:
   {"type":"start","language":..,"locale":..}  {"type":"text","text":...}  {"type":"talk","down":bool}
   {"type":"mode","voice":bool}  {"type":"permission","id":..,"allow":bool}  {"type":"end"}
Server → browser:  JSON {"type":"ready"|"line"|"audio"|"line_end"|"stop_audio"|"user_partial"|"user_final"|
   "state"|"end_call"|"error"}; audio is base64 PCM16 24 kHz.

Turns: push to talk. Pressing the talk button ("talk" down) cuts Ellis off at any point in any line -- no line
is protected from interruption -- and starts collecting Ink-2's transcript; releasing it submits what was said
while held. Tap to talk (the chat's mic button) ends TAP_SILENCE_S after the last new word instead; a tap mid-turn
only mutes. Typed text is a turn too and cuts Ellis off the same way. Every turn goes through the in-loop keyword
check (inside the liaison) before anything else sees it.
Ellis only ever speaks with Cartesia's voice. When Sonic is unreachable, lines are captions only; when Ink-2 is,
the applicant types.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...config import settings
from ...db import Case, session_scope
from ...services import auth, languages
from ...voice import cartesia
from ...voice.client import InProcessClient
from ...voice.liaison import Say
from ...voice.llm_liaison import LlmLiaison
from ..deps import APPLICANT_COOKIE

log = logging.getLogger("ellis.voice")
router = APIRouter(tags=["voice"])
# After the talk button is let go, send as soon as Ink-2 closes the turn: measured 0.6-1.4 s after the last word,
# with the full text arriving together with turn.eager_end. ponytail: two knobs, not a model --
# START_GRACE_S: a short "yes" only opens a turn ~0.5 s after it's said, so wait that long when nothing's heard yet;
# MAX_WAIT_S: never hold the message longer than this (raise both if endings get clipped).
PTT_START_GRACE_S = 1.0
PTT_MAX_WAIT_S = 2.5
# Tap to talk ends once no new word has come for this long (about what Gemini Live waits), so a long think isn't cut
# off. ponytail: a fixed wait, not Ink-2's turn detection; raise it if thinkers still get cut off.
TAP_SILENCE_S = 3.0
# ink-whisper (languages Ink-2 doesn't hear) has no turn detection: talk-up sends "finalize" and waits for
# flush_done, which takes longer than Ink-2's turn close
PTT_MANUAL_MAX_WAIT_S = 4.0


class VoiceSession:
    def __init__(self, ws: WebSocket, case_id: str):
        self.ws = ws
        self.case_id = case_id
        self.liaison: LlmLiaison | None = None
        self.q: asyncio.Queue[Say] = asyncio.Queue()
        self.current: dict[str, Any] | None = None
        self.last_interrupt: dict[str, Any] | None = None
        self.tts: cartesia.TTS | None = None
        self.stt: cartesia.STT | None = None
        self.stt_task: asyncio.Task | None = None
        self.patient = False
        self.opening = False  # Ellis's first line is still being prepared
        self.want_voice = True  # talking (vs. typing): silence only means "gone" when they talk
        self.talk: dict[str, Any] | None = None  # transcript so far while the talk button is held (+ tail)
        self.nudges = 0  # silence check-ins since the applicant last did something
        self.seq = 0  # turns sent so far: a reply that a newer turn overtook is never spoken
        self.lock = asyncio.Lock()
        self.last_line_end = time.time()
        self.user_active = False
        self.closed = False
        self.tasks: list[asyncio.Task] = []

    async def send(self, msg: dict) -> None:
        if not self.closed:
            try:
                await self.ws.send_json(msg)
            except Exception:  # noqa: BLE001
                self.closed = True

    async def run(self) -> None:
        start = await self.ws.receive_json()
        self.want_voice = start.get("voice") is not False
        # The case's persisted language is the fallback when the client doesn't specify one, so a session never
        # silently switches language on an applicant.
        def case_prefs() -> tuple[str, bool, str | None]:  # a database round trip: off the event loop
            with session_scope() as cs_s:
                case = cs_s.get(Case, self.case_id)
                st = (case.settings or {}) if case else {}
                return ((case.language if case and case.language else languages.DEFAULT_LOCALE),
                        bool(st.get("patient_mode")), st.get("voice_id"))
        case_locale, patient, voice_id = await asyncio.to_thread(case_prefs)
        # the language and accent Ellis talks in: what the client asked for, else what the case has
        locale = (languages.normalize(start.get("locale")) or languages.normalize(case_locale)
                  or languages.DEFAULT_LOCALE)
        language = languages.base(locale)
        if not settings.anthropic_api_key:
            await self.send({"type": "error", "message": "Ellis can't talk right now: this server has no "
                             "ANTHROPIC_API_KEY."})
            return
        self.liaison = LlmLiaison(InProcessClient(self.case_id), language=language, channel="voice")
        # The session opens (no model call) while Cartesia connects, each on its own: no Ink-2 only means typing,
        # and Ellis keeps Sonic's voice. Then the applicant can talk at once; the opening line follows.
        self.patient = patient
        connects = [self._connect("tts", cartesia.TTS(locale=locale, voice_id=voice_id)),
                    self._connect_stt(locale)] if settings.cartesia_api_key else []
        await asyncio.gather(asyncio.to_thread(self.liaison.begin), *connects)
        if self.tts:
            self.tts.speed = self.liaison.cfg["tts"]["speed"]
        await self.send({"type": "ready", "mode": "voice" if self.stt else "text", "cartesia": bool(self.tts),
                         "sample_rate_in": cartesia.STT_RATE, "sample_rate_out": cartesia.TTS_RATE,
                         "patient_mode": patient, "voice_unavailable": self.tts is None,
                         "talk_unavailable": self.stt is None})
        self.tasks.append(asyncio.create_task(self.speaker()))
        self.tasks.append(asyncio.create_task(self.watchdog()))
        if self.stt:
            self.stt_task = asyncio.create_task(self.stt_loop())
        self.opening = True
        await self.send({"type": "state", "state": "thinking"})
        self.tasks.append(asyncio.create_task(self.open(bool(start.get("disclosure_shown")))))
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    # ink-whisper transcribes whatever it gets: only what is said while the button is held
                    manual = getattr(self.stt, "manual", False)
                    if self.stt and (not manual or (self.talk is not None and not self.talk["finishing"])):
                        await self.stt.send_audio(msg["bytes"])
                    continue
                if msg.get("text"):
                    data = json.loads(msg["text"])
                    await self.on_client(data)
                    if data.get("type") == "end":
                        break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self.shutdown()

    async def open(self, disclosure_shown: bool) -> None:
        """Ellis's first line, prepared after `ready` so the applicant can already talk or type. It holds the turn
        lock: a turn sent meanwhile waits for it, and the model is told that turn came before they heard it."""
        lines: list[Say] = []
        try:
            async with self.lock:
                lines = await asyncio.to_thread(self.liaison.start, disclosure_shown)
        except Exception:  # noqa: BLE001 - the applicant can still talk; the next turn answers
            log.exception("opening failed")
        finally:
            self.opening = False
            self.last_line_end = time.time()  # silence check-ins count from now, not from connecting
        for ln in lines:
            await self.q.put(ln)
        if not lines and self.current is None and not self.user_active:
            await self.send({"type": "state", "state": "listening"})

    async def _connect_stt(self, locale: str) -> None:
        """The speech-to-text model that hears this language (none: the applicant types)."""
        model = languages.stt_model(locale)
        if model is None:
            log.info("no speech-to-text for %s: typing only", locale)
            return
        await self._connect("stt", cartesia.STT(patient=self.patient, model=model, language=languages.base(locale)))

    async def _connect(self, kind: str, client) -> None:
        # ponytail: measured 6-14 s for a cold voice lookup plus handshake; past 20 s, captions/typing instead
        try:
            await asyncio.wait_for(client.connect(), 20)
            setattr(self, kind, client)
        except Exception as e:  # noqa: BLE001
            log.warning("Cartesia %s unavailable: %r", kind, e)  # repr: a TimeoutError's str() is empty

    async def on_client(self, data: dict) -> None:
        t = data.get("type")
        if t == "text":
            await self.turn(str(data.get("text", "")))
        elif t == "talk":
            if data.get("down"):
                self.talk = {"done": [], "partial": "", "uncertain": False, "open": False, "text": "", "last": 0.0,
                             "mode": "tap" if data.get("mode") == "tap" else "hold", "finishing": False}
                self.nudges = 0
                if self.talk["mode"] == "tap":
                    self.tasks.append(asyncio.create_task(self.tap_end(self.talk)))
                await self.user_started()
            elif self.talk is not None:
                self.tasks.append(asyncio.create_task(self.talk_up(self.talk)))  # don't block the mic frames
        elif t == "mode":
            self.want_voice = bool(data.get("voice"))
        elif t == "permission" and self.liaison:
            async with self.lock:
                lines = await asyncio.to_thread(self.liaison.permission, str(data.get("id")), bool(data.get("allow")))
            await self.retune()
            self.nudges = 0
            for ln in lines:
                await self.q.put(ln)
        elif t == "end":
            if self.liaison and not self.liaison.ended:
                lines = await asyncio.to_thread(self.liaison.close)
                for ln in lines:
                    await self.q.put(ln)
                await asyncio.sleep(0.2)

    async def user_started(self) -> None:
        """The applicant started talking: Ellis stops, wherever it is in whatever line."""
        self.user_active = True
        cur = self.current
        if cur and not cur["interrupted"]:
            elapsed_ms = (time.time() - cur.get("audio_t0", time.time())) * 1000
            word = cartesia.word_at(cur["timestamps"], elapsed_ms)[0] if cur.get("timestamps") else None
            self.last_interrupt = {"field": cur.get("field"), "word": word, "at": time.time()}
            await self.cut(cur)
        await self.send({"type": "state", "state": "listening"})

    async def cut(self, cur: dict) -> None:
        """Stop the line being spoken now, and drop the rest of that reply."""
        cur["interrupted"] = True
        while not self.q.empty():
            self.q.get_nowait()
        if self.tts:
            await self.tts.cancel()
        await self.send({"type": "stop_audio", "line_id": cur["id"]})

    async def talk_up(self, talk: dict) -> None:
        """Button released, or Ink-2 closed a tap-to-talk turn: send what was said once the turn is closed."""
        if talk.get("finishing"):
            return
        talk["finishing"] = True
        t_up, max_wait = time.time(), PTT_MAX_WAIT_S
        if self.stt and getattr(self.stt, "manual", False):  # no turn detection: flush what was said, wait for it
            talk["open"] = talk["flushing"] = True
            max_wait = PTT_MANUAL_MAX_WAIT_S
            try:
                await self.stt.finalize()
            except Exception as e:  # noqa: BLE001 - send what arrived
                log.warning("stt finalize failed: %r", e)
                talk["open"] = talk["flushing"] = False
        while time.time() - t_up < max_wait:
            heard = talk["done"] or talk["partial"]
            if not talk["open"] and (heard or time.time() - t_up > PTT_START_GRACE_S):
                break
            await asyncio.sleep(0.02)
        if self.talk is talk:
            self.talk = None
        self.user_active = False
        text = " ".join(talk["done"] + [talk["partial"]]).strip()
        if text:
            await self.turn(text, uncertain=talk["uncertain"], spoken=True)
        else:
            await self.send({"type": "user_partial", "text": ""})
            await self.send({"type": "state", "state": "listening"})

    async def tap_end(self, talk: dict) -> None:
        """Tap to talk: send what was said TAP_SILENCE_S after the last new word, however long they think before it."""
        while self.talk is talk and not talk["finishing"]:
            if talk["text"] and time.time() - talk["last"] > TAP_SILENCE_S:
                await self.talk_up(talk)
            await asyncio.sleep(0.1)

    async def retune(self) -> None:
        """A setting the applicant just allowed (language, accent, voice speed) applies from the next line spoken."""
        cfg = self.liaison.cfg if self.liaison else {}
        if "tts" not in cfg:
            return
        if self.tts:
            self.tts.speed = cfg["tts"]["speed"]
            chosen = cfg.get("voice_id")
            if cfg["locale"] != self.tts.locale or (chosen and chosen != self.tts.voice_id):
                try:
                    self.tts.voice_id = chosen or await cartesia.voice_id_for(cfg["locale"]) or self.tts.voice_id
                    self.tts.locale = cfg["locale"]
                except Exception as e:  # noqa: BLE001 - keep the old voice rather than go silent
                    log.warning("voice for %s unavailable: %s", cfg["locale"], e)
        if settings.cartesia_api_key:
            await self.relisten(cfg["locale"])

    async def relisten(self, locale: str) -> None:
        """A new language may need another speech-to-text model (Ink-2 hears five languages, ink-whisper the rest)."""
        model, lang = languages.stt_model(locale), languages.base(locale)
        if self.stt and (self.stt.model, self.stt.language) == (model, lang):
            return
        old, self.stt = self.stt, None
        if self.stt_task:
            self.stt_task.cancel()
            self.stt_task = None
        if old:
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass
        await self._connect_stt(locale)
        if self.stt:
            self.stt_task = asyncio.create_task(self.stt_loop())

    async def stt_loop(self) -> None:
        """Ink-2 is only the transcriber: what counts is what was said while the talk button was held."""
        try:
            async for ev in self.stt.events():
                t, talk = ev.get("type"), self.talk
                if t == "error":
                    await self.send({"type": "error", "message": "voice service error"})
                if talk is None:
                    continue
                # "open": Ink-2 may still be adding words. eager_end carries the full text and, once the button
                # is let go, nothing can follow it; an update or resume reopens the turn while they still talk.
                if t == "turn.start":
                    talk["partial"], talk["open"] = "", True
                elif t == "turn.update":
                    talk["partial"], talk["open"] = ev.get("transcript", ""), True
                elif t == "turn.eager_end":
                    talk["partial"], talk["open"] = ev.get("transcript", ""), False
                elif t == "turn.resume":
                    # Ink-2 thought they were done, then heard more: an indirect hesitation signal (its events
                    # carry no confidence score)
                    talk["uncertain"], talk["open"] = True, True
                elif t == "turn.end":
                    talk["done"].append(ev.get("transcript", ""))
                    talk["partial"], talk["open"] = "", bool(talk.get("flushing"))
                elif t == "turn.flushed":  # ink-whisper: everything said while held has arrived
                    talk["open"] = talk["flushing"] = False
                else:
                    continue
                text = " ".join(talk["done"] + [talk["partial"]]).strip()
                if text and text != talk["text"]:  # a new word: tap_end's clock starts over
                    talk["text"], talk["last"] = text, time.time()
                await self.send({"type": "user_partial", "text": text})
        except Exception as e:  # noqa: BLE001
            log.warning("stt loop ended: %s", e)

    async def turn(self, text: str, uncertain: bool = False, spoken: bool = False) -> None:
        text = (text or "").strip()
        if not text or self.liaison is None or self.liaison.ended:
            return
        if self.current and not self.current["interrupted"]:
            await self.cut(self.current)  # a typed message cuts Ellis off too
        await self.send({"type": "user_final", "text": text, "spoken": spoken})
        await self.send({"type": "state", "state": "thinking"})
        field = word = None
        li = self.last_interrupt
        if li and time.time() - li["at"] < 30:
            field, word = li["field"], li["word"]
        self.last_interrupt = None
        self.nudges = 0
        self.seq += 1
        seq, unheard = self.seq, self.lock.locked()  # locked: the reply to their last turn isn't out yet
        async with self.lock:
            lines = await asyncio.to_thread(self.liaison.handle, text, field, word, uncertain, unheard)
        if seq != self.seq:
            # they spoke again while this reply was being prepared: the newer turn answers both.
            # ponytail: the dropped reply stays in the transcript; mark it there if it misleads a reviewer
            return
        for ln in lines:
            await self.q.put(ln)

    async def speaker(self) -> None:
        while True:
            line = await self.q.get()
            lid = uuid.uuid4().hex[:10]
            cur = {"id": lid, "field": line.field, "timestamps": {}, "interrupted": False}
            self.current = cur
            await self.send({"type": "state", "state": "speaking"})
            await self.send({"type": "line", "id": lid, **line.as_dict()})
            if self.tts:  # no Sonic: the line is a caption, nothing to wait for
                try:
                    cur["audio_t0"] = time.time()
                    async for part in self.tts.speak(line.text):
                        if cur["interrupted"]:
                            continue  # drain the cancelled context
                        if "audio" in part:
                            await self.send({"type": "audio", "line_id": lid,
                                             "data": base64.b64encode(part["audio"]).decode()})
                        elif "timestamps" in part:
                            ts = part["timestamps"]
                            for k in ("words", "start", "end"):
                                cur["timestamps"].setdefault(k, []).extend(ts.get(k, []))
                    # wait roughly for playback to finish before the next line (audio is real-time)
                    dur = (cur["timestamps"].get("end") or [0])[-1] if cur["timestamps"] else 0
                    end = cur["audio_t0"] + dur
                    while time.time() < end and not cur["interrupted"]:
                        await asyncio.sleep(0.05)
                except Exception as e:  # noqa: BLE001
                    log.warning("tts failed: %s", e)
            await self.send({"type": "line_end", "line_id": lid, "interrupted": cur["interrupted"]})
            self.last_line_end = time.time()
            if line.end_call:
                await self.send({"type": "end_call"})
            if self.q.empty():
                self.current = None
                await self.send({"type": "state", "state": "listening"})

    async def watchdog(self) -> None:
        """Quiet after Ellis speaks: check in a few times, each wait (call_config) counted from Ellis's last line
        and longer than the one before, the last one offering another day; then quiet until the applicant does
        something. Only when they talk: someone typing isn't gone, just typing."""
        while not self.closed:
            await asyncio.sleep(1)
            if (not self.want_voice or self.liaison is None or self.liaison.ended or self.current is not None
                    or self.user_active or self.opening):
                continue
            waits = self.liaison.cfg.get("silence_thresholds_s", [15, 45, 120])
            if self.nudges >= len(waits) or time.time() - self.last_line_end < waits[self.nudges]:
                continue
            self.nudges += 1
            lines = await asyncio.to_thread(self.liaison.silence, waits[self.nudges - 1], self.nudges == len(waits))
            for ln in lines:
                await self.q.put(ln)

    async def shutdown(self) -> None:
        self.closed = True
        for t in [*self.tasks, self.stt_task]:
            if t is not None:
                t.cancel()
        for c in (self.stt, self.tts):
            if c is not None:
                try:
                    await c.close()
                except Exception:  # noqa: BLE001
                    pass
        if self.liaison and not self.liaison.ended:
            try:
                await asyncio.to_thread(self.liaison.c.session_end)
            except Exception:  # noqa: BLE001
                pass


@router.websocket("/api/a/voice")
async def voice(ws: WebSocket):
    payload = auth.unsign(ws.cookies.get(APPLICANT_COOKIE))
    if not payload or payload.get("kind") != "applicant":
        await ws.close(code=4401)
        return
    await ws.accept()
    await VoiceSession(ws, payload["case_id"]).run()
