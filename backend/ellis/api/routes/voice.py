"""Applicant voice session: WS /api/a/voice.

Browser → server:  binary PCM16 mono 16 kHz mic frames, or JSON:
   {"type":"start","mode":"voice"|"text"}  {"type":"text","text":...}  {"type":"interrupt","line_id":..,
   "position_ms":..|"word":..}  {"type":"spoken","line_id":..}  {"type":"end"}
Server → browser:  JSON {"type":"ready"|"line"|"audio"|"line_end"|"stop_audio"|"user_partial"|"user_final"|
   "state"|"end_call"|"error"}; audio is base64 PCM16 24 kHz.

Turn handling (spec): turn.start during an interruptible line stops TTS and records the interrupted word from
Sonic word timestamps; during a locked line the applicant's turn is held until the line finishes. Every final
transcript goes through the in-loop keyword check (inside the liaison) before anything else sees it.
When Cartesia is unreachable the session runs in text mode: captions, typed or browser-recognized turns, and
the browser speaks lines with its own es-MX voice.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ...config import settings
from ...db import Case, session_scope
from ...services import auth
from ...services.case_service import today
from ...voice import cartesia
from ...voice.client import InProcessClient
from ...voice.liaison import Liaison, Say
from ..deps import APPLICANT_COOKIE

log = logging.getLogger("ellis.voice")
router = APIRouter(tags=["voice"])


class VoiceSession:
    def __init__(self, ws: WebSocket, case_id: str):
        self.ws = ws
        self.case_id = case_id
        self.liaison: Liaison | None = None
        self.q: asyncio.Queue[Say] = asyncio.Queue()
        self.current: dict[str, Any] | None = None
        self.held: list[str] = []
        self.last_interrupt: dict[str, Any] | None = None
        self.tts: cartesia.TTS | None = None
        self.stt: cartesia.STT | None = None
        self.mode = "text"
        self.lock = asyncio.Lock()
        self.last_line_end = time.time()
        self.user_active = False
        self.silence_said: set[int] = set()
        self.closed = False
        self.tasks: list[asyncio.Task] = []
        self.resume_count = 0  # turn.resume events this turn: the model thought the applicant was done, then
                               # detected they kept talking -- a real (if indirect) uncertainty signal, since
                               # Cartesia's turn events carry no confidence/probability field to read directly

    async def send(self, msg: dict) -> None:
        if not self.closed:
            try:
                await self.ws.send_json(msg)
            except Exception:  # noqa: BLE001
                self.closed = True

    async def run(self) -> None:
        start = await self.ws.receive_json()
        want_voice = start.get("mode", "voice") == "voice"
        # The case's persisted language is the fallback when the client doesn't specify one (e.g. an older
        # client, or a returning session whose frontend state hasn't loaded the case yet), so a session never
        # silently reverts to Spanish for an applicant who chose English.
        case_locale = "es-MX"
        with session_scope() as cs_s:
            case = cs_s.get(Case, self.case_id)
            if case and case.language:
                case_locale = case.language
        default_lang = "en" if case_locale.startswith("en") else "es"
        language = start.get("language") if start.get("language") in ("es", "en") else default_lang
        locale = start.get("locale") or (case_locale if language == default_lang else
                                         ("en-US" if language == "en" else "es-MX"))
        from ...voice.humanize import humanizer
        from ...voice.llm import extractor
        self.liaison = Liaison(InProcessClient(self.case_id), today=today(),
                               channel="voice" if want_voice else "text", llm=extractor(),
                               humanizer=humanizer(), language=language)
        lines = await asyncio.to_thread(self.liaison.start)
        patient = bool(self.liaison.cfg.get("patient_mode"))
        cartesia_ok = False
        if want_voice and settings.cartesia_api_key:
            try:
                self.tts = cartesia.TTS(speed=0.85 if patient else 1.0, locale=locale)
                await asyncio.wait_for(self.tts.connect(), 8)
                self.stt = cartesia.STT(patient=patient)
                await asyncio.wait_for(self.stt.connect(), 8)
                cartesia_ok = True
            except Exception as e:  # noqa: BLE001
                log.warning("Cartesia unavailable, falling back to text mode: %s", e)
                self.tts = self.stt = None
        self.mode = "voice" if cartesia_ok else "text"
        await self.send({"type": "ready", "mode": self.mode, "cartesia": cartesia_ok,
                         "sample_rate_in": cartesia.STT_RATE, "sample_rate_out": cartesia.TTS_RATE,
                         "patient_mode": patient, "client_tts": not cartesia_ok,
                         "voice_unavailable": want_voice and not cartesia_ok})
        self.tasks.append(asyncio.create_task(self.speaker()))
        self.tasks.append(asyncio.create_task(self.watchdog()))
        if self.stt:
            self.tasks.append(asyncio.create_task(self.stt_loop()))
        for ln in lines:
            await self.q.put(ln)
        try:
            while True:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if self.stt:
                        await self.stt.send_audio(msg["bytes"])
                    continue
                if msg.get("text"):
                    import json
                    data = json.loads(msg["text"])
                    await self.on_client(data)
                    if data.get("type") == "end":
                        break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self.shutdown()

    async def on_client(self, data: dict) -> None:
        t = data.get("type")
        if t == "text":
            await self.turn(str(data.get("text", "")))
        elif t == "interrupt":
            line = self.current if self.current and self.current["id"] == data.get("line_id") else None
            if line is not None and not line["locked"]:
                word = data.get("word")
                if word is None and data.get("position_ms") is not None and line.get("timestamps"):
                    word, _ = cartesia.word_at(line["timestamps"], float(data["position_ms"]))
                line["interrupted"] = True
                self.last_interrupt = {"field": line.get("field"), "word": word, "at": time.time()}
                if self.tts:
                    await self.tts.cancel()
        elif t == "speech_start":
            await self.user_started()
        elif t == "spoken":
            if self.current and self.current["id"] == data.get("line_id"):
                self.current["spoken_ack"].set()
        elif t == "end":
            if self.liaison and not self.liaison.ended:
                lines = await asyncio.to_thread(self.liaison.close)
                for ln in lines:
                    await self.q.put(ln)
                await asyncio.sleep(0.2)

    async def user_started(self) -> None:
        """turn.start: barge-in on an interruptible line; ignored (held) on a locked one."""
        self.user_active = True
        self.resume_count = 0
        cur = self.current
        if cur and not cur["locked"] and not cur.get("interrupted"):
            cur["interrupted"] = True
            elapsed_ms = (time.time() - cur.get("audio_t0", time.time())) * 1000
            word = None
            if cur.get("timestamps"):
                word, _ = cartesia.word_at(cur["timestamps"], elapsed_ms)
            self.last_interrupt = {"field": cur.get("field"), "word": word, "at": time.time()}
            if self.tts:
                await self.tts.cancel()
            await self.send({"type": "stop_audio", "line_id": cur["id"]})
        await self.send({"type": "state", "state": "listening"})

    async def stt_loop(self) -> None:
        try:
            async for ev in self.stt.events():
                t = ev.get("type")
                if t == "turn.start":
                    await self.user_started()
                elif t in ("turn.update", "turn.eager_end"):
                    await self.send({"type": "user_partial", "text": ev.get("transcript", "")})
                elif t == "turn.resume":
                    self.user_active = True
                    self.resume_count += 1
                elif t == "turn.end":
                    self.user_active = False
                    uncertain = self.resume_count > 0
                    self.resume_count = 0
                    await self.turn(ev.get("transcript", ""), uncertain=uncertain)
                elif t == "error":
                    await self.send({"type": "error", "message": "voice service error"})
        except Exception as e:  # noqa: BLE001
            log.warning("stt loop ended: %s", e)

    async def turn(self, text: str, uncertain: bool = False) -> None:
        text = (text or "").strip()
        if not text or self.liaison is None or self.liaison.ended:
            return
        if self.current and self.current["locked"] and not self.current["done"].is_set():
            self.held.append(text)  # locked line: keep speaking, handle the turn afterwards
            return
        await self.send({"type": "user_final", "text": text})
        await self.send({"type": "state", "state": "thinking"})
        field = word = None
        li = self.last_interrupt
        if li and time.time() - li["at"] < 30:
            field, word = li["field"], li["word"]
        self.last_interrupt = None
        self.silence_said.clear()
        async with self.lock:
            lines = await asyncio.to_thread(self.liaison.handle, text, field, word, uncertain)
        for ln in lines:
            await self.q.put(ln)

    async def speaker(self) -> None:
        while True:
            line = await self.q.get()
            lid = uuid.uuid4().hex[:10]
            cur = {"id": lid, "locked": line.locked, "field": line.field, "timestamps": {}, "interrupted": False,
                   "done": asyncio.Event(), "spoken_ack": asyncio.Event()}
            self.current = cur
            await self.send({"type": "state", "state": "speaking"})
            await self.send({"type": "line", "id": lid, **line.as_dict()})
            try:
                if self.tts:
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
                    remaining = dur - (time.time() - cur["audio_t0"])
                    if remaining > 0 and not cur["interrupted"]:
                        await self._sleep_unless_interrupted(cur, remaining)
                else:
                    # client speaks with its own voice; wait for its ack (bounded by an estimate)
                    est = min(2 + len(line.text) * 0.07, 30)
                    try:
                        await asyncio.wait_for(cur["spoken_ack"].wait(), timeout=est)
                    except asyncio.TimeoutError:
                        pass
            except Exception as e:  # noqa: BLE001
                log.warning("tts failed: %s", e)
            cur["done"].set()
            await self.send({"type": "line_end", "line_id": lid, "interrupted": cur["interrupted"]})
            self.last_line_end = time.time()
            if line.end_call:
                await self.send({"type": "end_call"})
            if self.q.empty():
                self.current = None
                await self.send({"type": "state", "state": "listening"})
                if self.held:
                    held, self.held = self.held, []
                    for t in held:
                        await self.turn(t)

    async def _sleep_unless_interrupted(self, cur: dict, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end and not cur["interrupted"]:
            await asyncio.sleep(0.05)

    async def watchdog(self) -> None:
        """Silence after a question: 'Tómese su tiempo' / repeat once / '¿Seguimos otro día?'."""
        while not self.closed:
            await asyncio.sleep(1)
            if self.liaison is None or self.liaison.ended or self.current is not None or self.user_active:
                continue
            silent = time.time() - self.last_line_end
            a, b, c = self.liaison.cfg.get("silence_thresholds_s", [8, 20, 60])
            for th in (a, b, c):
                if silent >= th and th not in self.silence_said:
                    self.silence_said.add(th)
                    lines = await asyncio.to_thread(self.liaison.silence, th)
                    for ln in lines:
                        await self.q.put(ln)
                    break

    async def shutdown(self) -> None:
        self.closed = True
        for t in self.tasks:
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
