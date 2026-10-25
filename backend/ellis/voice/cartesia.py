"""Cartesia clients for the in-house voice gateway (raw WebSocket APIs, per the cartesia SDK 4.2 source).

- Ink-2 streaming STT with turn detection (en es fr hi ja): wss://api.cartesia.ai/stt/turns/websocket
  (events: connected, turn.start, turn.update, turn.eager_end, turn.resume, turn.end)
- ink-whisper streaming STT for every other language, no turn detection: wss://api.cartesia.ai/stt/websocket
  (language=<code>; "finalize" flushes; events: transcript {is_final, text}, flush_done, done). STT translates
  them into the same turn.* events, so the session handles one shape.
- Sonic TTS WebSocket with word timestamps: wss://api.cartesia.ai/tts/websocket. Sonic 3.6+ takes the accent
  as `locale` (e.g. "es-MX", "fr-CA"); older models take the base `language`.
Auth is the Authorization: Bearer header plus cartesia-version. Which language goes where: services/languages.py.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import yaml

from ..config import CONFIG_DIR, settings

log = logging.getLogger("ellis.cartesia")

BASE = os.environ.get("CARTESIA_BASE_URL", "https://api.cartesia.ai")
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")
VERSION = os.environ.get("CARTESIA_VERSION", "2026-08-14")
STT_RATE = 16000
TTS_RATE = 24000


def headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.cartesia_api_key}", "cartesia-version": VERSION}


@lru_cache
def pronunciations() -> list[tuple[re.Pattern, str]]:
    data = yaml.safe_load((CONFIG_DIR / "pronunciation.yaml").read_text(encoding="utf-8")) or {}
    return [(re.compile(r"\b" + re.escape(k) + r"\b"), v) for k, v in data.items()]


def speakable(text: str) -> str:
    """Apply the pronunciation dictionary as text substitutions (used when no Cartesia dict id is configured)."""
    if os.environ.get("CARTESIA_PRONUNCIATION_DICT_ID"):
        return text
    for pat, rep in pronunciations():
        text = pat.sub(rep, text)
    return text


_voice_cache: dict[str, str] = {}
_list_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
LIST_TTL_S = 600


def _accent_locales(v: dict[str, Any], native_only: bool = False) -> list[str]:
    """A voice's locales: accents[].locale (current API), else the older locales[] / language fields."""
    out = [str(a.get("locale", "")) for a in v.get("accents") or [] if isinstance(a, dict)
           and (a.get("is_native") or not native_only)]
    if not out and not native_only:
        out = [str(x.get("locale", x) if isinstance(x, dict) else x) for x in v.get("locales") or []]
        out += [str(v.get("language", ""))]
    return [x for x in out if x]


async def voices(locale: str) -> list[dict[str, Any]]:
    """Sonic voices for a language or locale ('fr', 'fr-CA'), best first: recorded in this accent, then able to
    speak it, then the rest Cartesia lists for the language. Cached for LIST_TTL_S."""
    hit = _list_cache.get(locale)
    if hit and time.time() - hit[0] < LIST_TTL_S:
        return hit[1]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/voices", headers=headers(),
                        params={"limit": 100, "language": locale, "expand[]": "preview_file_url"})
        r.raise_for_status()
        data = r.json()
    found = data.get("data", data) if isinstance(data, dict) else data
    want, base_lang = locale.lower(), locale.split("-")[0].lower()

    def rank(v: dict[str, Any]) -> int:
        if want in (x.lower() for x in _accent_locales(v, native_only=True)):
            return 0
        locs = [x.lower() for x in _accent_locales(v)]
        return 1 if want in locs else 2 if any(x.split("-")[0] == base_lang for x in locs) else 3
    out = sorted(found or [], key=rank)
    _list_cache[locale] = (time.time(), out)
    return out


async def voice_id_for(locale: str = "es-MX") -> str | None:
    """Best Sonic voice id for a locale like 'es-MX' or 'fr-CA' (see voices()). CARTESIA_VOICE_ID pins the Spanish
    voice specifically (documented as such in .env.example) and is left alone for other languages so a fixed
    Spanish pin doesn't silently become the English voice too.
    """
    if locale.lower().startswith("es") and os.environ.get("CARTESIA_VOICE_ID"):
        return os.environ["CARTESIA_VOICE_ID"]
    if locale in _voice_cache:
        return _voice_cache[locale]
    found = await voices(locale)
    best = found[0]["id"] if found else None
    if best:
        _voice_cache[locale] = best
    return best


def uses_locale(model: str) -> bool:
    """Sonic 3.6 and later take the accent as `locale`; older models take the base `language`."""
    m = re.match(r"sonic-(\d+)(?:\.(\d+))?(?:-|$)", model)
    if not m:
        return model.startswith("sonic-preview")
    return (int(m[1]), int(m[2] or 0)) >= (3, 6)


async def warm_voices() -> None:
    """Look the voices up once at startup: /voices takes 3-9 s, too slow to pay inside a session's connect."""
    for loc in ("en-US", "es-MX"):
        try:
            await voice_id_for(loc)
        except Exception as e:  # noqa: BLE001 - a session will retry the lookup itself
            log.warning("voice lookup for %s failed: %r", loc, e)


class TTS:
    """One Sonic WebSocket per call; one context per spoken line."""

    def __init__(self, speed: float = 1.0, locale: str = "es-MX", voice_id: str | None = None):
        self.ws = None
        self.speed = speed
        self.locale = locale
        self.voice_id: str | None = voice_id  # the applicant's own choice, when they made one
        self.model = os.environ.get("CARTESIA_TTS_MODEL") or "sonic-3.6"

    async def connect(self) -> None:
        from websockets.asyncio.client import connect
        self.voice_id = self.voice_id or await voice_id_for(self.locale)
        if not self.voice_id:
            raise RuntimeError(f"no voice id for locale {self.locale!r} (set CARTESIA_VOICE_ID for Spanish)")
        self.ws = await connect(f"{WS_BASE}/tts/websocket", additional_headers=headers(), max_size=2 ** 24)

    async def speak(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """Yields {"audio": bytes} and {"words": [...], "start": [...], "end": [...]} until done."""
        ctx = str(uuid.uuid4())
        self.context_id = ctx
        req: dict[str, Any] = {
            "context_id": ctx, "model_id": self.model, "transcript": speakable(text),
            "voice": {"mode": "id", "id": self.voice_id},
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": TTS_RATE},
            "add_timestamps": True, "continue": False,
        }
        if uses_locale(self.model):
            req["locale"] = self.locale  # the accent: "es-MX", "fr-CA", or a bare language code
        else:
            req["language"] = self.locale.split("-")[0]
        if self.speed != 1.0:
            req["generation_config"] = {"speed": self.speed}
        if os.environ.get("CARTESIA_PRONUNCIATION_DICT_ID"):
            req["pronunciation_dict_id"] = os.environ["CARTESIA_PRONUNCIATION_DICT_ID"]
        await self.ws.send(json.dumps(req))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("context_id") not in (None, ctx):
                continue
            t = msg.get("type")
            if t == "chunk" and msg.get("data"):
                yield {"audio": base64.b64decode(msg["data"])}
            elif t == "timestamps" and msg.get("word_timestamps"):
                yield {"timestamps": msg["word_timestamps"]}
            elif t == "error":
                raise RuntimeError(msg.get("message") or msg.get("title") or "tts error")
            if msg.get("done") or t == "done":
                return

    async def cancel(self) -> None:
        if self.ws is not None and getattr(self, "context_id", None):
            try:
                await self.ws.send(json.dumps({"context_id": self.context_id, "cancel": True}))
            except Exception:  # noqa: BLE001
                pass

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()


class STT:
    """Ink-2 with turn detection, or ink-whisper (manual) for the languages Ink-2 doesn't hear.
    Audio in: 16 kHz pcm_s16le binary frames (~100 ms)."""

    def __init__(self, patient: bool = False, model: str = "ink-2", language: str = "en"):
        self.ws = None
        self.patient = patient
        self.model = model
        self.language = language
        self.manual = model == "ink-whisper"  # no turn detection: the session flushes on talk-up (finalize)

    async def connect(self) -> None:
        from websockets.asyncio.client import connect
        if self.manual:
            q = f"model={self.model}&language={self.language}&encoding=pcm_s16le&sample_rate={STT_RATE}"
            self.ws = await connect(f"{WS_BASE}/stt/websocket?{q}", additional_headers=headers(), max_size=2 ** 22)
            return
        # CARTESIA_STT_MODEL picks among the turn-detection models (ink-2, ink-preview)
        params = {"model": os.environ.get("CARTESIA_STT_MODEL") or self.model, "encoding": "pcm_s16le",
                  "sample_rate": str(STT_RATE)}
        # Turn detection is configurable on this endpoint (turn_start_threshold 0.5-0.9 default 0.8,
        # turn_eager_end_threshold 0.3-0.8 default 0.6, turn_end_threshold 0.05-0.5 default 0.3,
        # turn_end_timeout_ms 640-11200 default 5600; thresholds must stay end < eager_end < start).
        # Cartesia's defaults are tuned for brisk back-and-forth; this applicant population (uncertain
        # life history, often in a second language) benefits from more patience before the model decides
        # a turn is over, and from a more sensitive start threshold so barge-in actually registers instead
        # of requiring a loud, early interruption. Patient mode (handoff: Patient profile) goes further.
        if self.patient:
            params.update({"turn_start_threshold": "0.6", "turn_eager_end_threshold": "0.4",
                           "turn_end_threshold": "0.1", "turn_end_timeout_ms": "9000"})
        else:
            params.update({"turn_start_threshold": "0.65", "turn_eager_end_threshold": "0.5",
                           "turn_end_threshold": "0.2", "turn_end_timeout_ms": "6500"})
        for kv in filter(None, os.environ.get("CARTESIA_STT_EXTRA_PARAMS", "").split("&")):
            k, _, v = kv.partition("=")
            params[k] = v
        q = "&".join(f"{k}={v}" for k, v in params.items())
        self.ws = await connect(f"{WS_BASE}/stt/turns/websocket?{q}", additional_headers=headers(), max_size=2 ** 22)

    async def send_audio(self, pcm: bytes) -> None:
        await self.ws.send(pcm)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        async for raw in self.ws:
            if isinstance(raw, bytes):
                continue
            msg = json.loads(raw)
            if not self.manual:
                yield msg
                continue
            # ink-whisper -> the turn events the session understands: a final transcript closes a piece of the
            # turn (more may follow while the button is held); flush_done says everything said has arrived
            t = msg.get("type")
            if t == "transcript" and msg.get("text", "").strip():
                yield {"type": "turn.end" if msg.get("is_final") else "turn.update", "transcript": msg["text"].strip()}
            elif t == "flush_done":
                yield {"type": "turn.flushed"}
            elif t == "error":
                yield msg
            elif t == "done":
                return

    async def finalize(self) -> None:
        """ink-whisper: transcribe everything sent so far now (answered with flush_done)."""
        if self.manual and self.ws is not None:
            await self.ws.send("finalize")

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.send("close" if self.manual else json.dumps({"type": "close"}))
            except Exception:  # noqa: BLE001
                pass
            await self.ws.close()


def word_at(timestamps: dict[str, list], position_ms: float) -> tuple[str | None, int | None]:
    """The word being spoken at a playback position (barge-in mapping from Sonic word timestamps)."""
    words = timestamps.get("words") or []
    starts = timestamps.get("start") or []
    pos = position_ms / 1000.0
    idx = None
    for i, st in enumerate(starts):
        if st <= pos:
            idx = i
        else:
            break
    if idx is None:
        return None, None
    return words[idx], idx + 1
