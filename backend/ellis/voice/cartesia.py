"""Cartesia clients for the in-house voice gateway (raw WebSocket APIs, per the cartesia SDK 4.2 source).

- Ink-2 streaming STT with turn detection: wss://api.cartesia.ai/stt/turns/websocket
  (events: connected, turn.start, turn.update, turn.eager_end, turn.resume, turn.end)
- Sonic TTS WebSocket with word timestamps: wss://api.cartesia.ai/tts/websocket
Auth is the Authorization: Bearer header plus cartesia-version.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
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


async def voice_id_for(locale: str = "es-MX") -> str | None:
    """Best Sonic voice id for a locale like 'es-MX' or 'en-US': an exact locale match, else the first
    voice whose language matches the base code (e.g. any 'es' voice). CARTESIA_VOICE_ID pins the Spanish
    voice specifically (documented as such in .env.example) and is left alone for other languages so a
    fixed Spanish pin doesn't silently become the English voice too.
    """
    if locale.lower().startswith("es") and os.environ.get("CARTESIA_VOICE_ID"):
        return os.environ["CARTESIA_VOICE_ID"]
    if locale in _voice_cache:
        return _voice_cache[locale]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/voices", headers=headers(), params={"limit": 100})
        r.raise_for_status()
        data = r.json()
    voices = data.get("data", data) if isinstance(data, dict) else data
    base_lang = locale.split("-")[0].lower()
    best = None
    for v in voices or []:
        locales = [str(x.get("locale", x) if isinstance(x, dict) else x) for x in (v.get("locales") or [])]
        lang = str(v.get("language", ""))
        if any(lc.lower() == locale.lower() for lc in locales):
            best = v["id"]
            break
        if best is None and (lang.lower() == base_lang or any(lc.lower().startswith(base_lang) for lc in locales)):
            best = v["id"]
    if best:
        _voice_cache[locale] = best
    return best


class TTS:
    """One Sonic WebSocket per call; one context per spoken line."""

    def __init__(self, speed: float = 1.0, locale: str = "es-MX"):
        self.ws = None
        self.speed = speed
        self.locale = locale
        self.voice_id: str | None = None
        self.model = os.environ.get("CARTESIA_TTS_MODEL", "sonic-3")

    async def connect(self) -> None:
        from websockets.asyncio.client import connect
        self.voice_id = await voice_id_for(self.locale)
        if not self.voice_id:
            raise RuntimeError(f"no voice id for locale {self.locale!r} (set CARTESIA_VOICE_ID for Spanish)")
        self.ws = await connect(f"{WS_BASE}/tts/websocket", additional_headers=headers(), max_size=2 ** 24)

    async def speak(self, text: str) -> AsyncIterator[dict[str, Any]]:
        """Yields {"audio": bytes} and {"words": [...], "start": [...], "end": [...]} until done."""
        ctx = str(uuid.uuid4())
        self.context_id = ctx
        req: dict[str, Any] = {
            "context_id": ctx, "model_id": self.model, "transcript": speakable(text),
            "voice": {"mode": "id", "id": self.voice_id}, "language": self.locale.split("-")[0],
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": TTS_RATE},
            "add_timestamps": True, "continue": False,
        }
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
    """Ink-2 with turn detection. Audio in: 16 kHz pcm_s16le binary frames (~100 ms)."""

    def __init__(self, patient: bool = False):
        self.ws = None
        self.patient = patient

    async def connect(self) -> None:
        from websockets.asyncio.client import connect
        params = {"model": os.environ.get("CARTESIA_STT_MODEL", "ink-2"), "encoding": "pcm_s16le",
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
            yield json.loads(raw)

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.send(json.dumps({"type": "close"}))
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
