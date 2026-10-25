"""The languages Ellis talks in (config/languages.yaml): every language and accent Cartesia's Sonic speaks.

A case stores a locale (case.language, e.g. "fr-CA"). Three things follow from it:
- the conversation: Ellis talks in that language and accent (Claude replies in it, Sonic speaks it);
- listening: which Cartesia speech-to-text model can hear it (stt);
- Ellis's own screen and server text, which exists in English and Spanish only (copy_lang): Spanish for es-*,
  English for everything else.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import yaml_config

COPY_LANGS = ("en", "es")  # languages Ellis's own text is written in
DEFAULT_LOCALE = "en-US"


@lru_cache
def _langs() -> dict[str, dict[str, Any]]:
    return {str(k): v for k, v in (yaml_config("languages.yaml") or {}).items()}


def base(locale: str | None) -> str:
    """'fr-CA' -> 'fr' (unknown or empty -> 'en')."""
    code = (locale or "").replace("_", "-").split("-")[0].lower()
    return code if code in _langs() else "en"


def normalize(locale: str | None) -> str | None:
    """A supported locale in Cartesia's spelling ('fr_ca' -> 'fr-CA', 'fr' -> its default 'fr-FR'), else None."""
    if not locale:
        return None
    want = locale.replace("_", "-").lower()
    lang = _langs().get(want.split("-")[0])
    if lang is None:
        return None
    codes = [loc["code"] for loc in lang["locales"]]
    if "-" not in want:
        return codes[0]
    return next((c for c in codes if c.lower() == want), None)


def supported(locale: str | None) -> bool:
    return normalize(locale) is not None


def copy_lang(locale: str | None) -> str:
    """The language for Ellis's own text: 'es' for Spanish, 'en' for every other language."""
    return "es" if base(locale) == "es" else "en"


def info(locale: str | None) -> dict[str, Any]:
    return _langs()[base(locale)]


def name(locale: str | None) -> str:
    """English name with the accent when the language has several: 'French (Canada)', 'Spanish (México)'."""
    lang, loc = info(locale), normalize(locale)
    label = next((x.get("label") for x in lang["locales"] if x["code"] == loc), None)
    return f"{lang['name']} ({label})" if label and len(lang["locales"]) > 1 else lang["name"]


def native_name(locale: str | None) -> str:
    lang, loc = info(locale), normalize(locale)
    label = next((x.get("label") for x in lang["locales"] if x["code"] == loc), None)
    return f"{lang['native']} ({label})" if label and len(lang["locales"]) > 1 else lang["native"]


def stt_model(locale: str | None) -> str | None:
    """Which Cartesia speech-to-text model hears this language; None when none does (typing only)."""
    m = info(locale).get("stt")
    return None if m in (None, "none") else m


def is_rtl(locale: str | None) -> bool:
    return bool(info(locale).get("rtl"))


def options() -> dict[str, str]:
    """Every supported locale -> its own name, e.g. {'fr-CA': 'Français (Canada)'} (settings choices)."""
    return {loc["code"]: native_name(loc["code"]) for lang in _langs().values() for loc in lang["locales"]}


def catalog() -> list[dict[str, Any]]:
    """For the language pickers: one entry per language, in the order of the file."""
    return [{"code": code, "name": lang["name"], "native": lang["native"], "rtl": bool(lang.get("rtl")),
             "voice_input": stt_model(code) is not None, "copy_lang": copy_lang(code),
             "locales": [{"code": loc["code"], "label": loc.get("label")} for loc in lang["locales"]]}
            for code, lang in _langs().items()]
