"""Optional Claude rephrasing pass over the liaison's scripted lines: makes the fixed wording sound like
a person, not a script. Applied only to generic chrome (acknowledgments, free-form questions) -- never to
locked lines (disclosure, stop-script), official N-400 question text, or read-backs, which must stay exact
for legal/accuracy reasons. Runs strictly after the rules engine has already decided what to say and
recorded any fact/flag/hedge; it can only change wording, never state. Enabled when ANTHROPIC_API_KEY is set.
"""

from __future__ import annotations

from ..config import settings

GENERIC_KINDS = {"say", "question"}

PROMPT = """Rephrase this line from a voice assistant helping someone prepare their N-400 citizenship \
application, so it sounds like a warm, natural person speaking, not a script. Keep the exact same \
meaning and language ({lang}). Never add, remove, or change any fact, name, date, number, or question. \
Keep it about the same length. Return ONLY the rephrased line, nothing else.

Line: {text}"""


class Humanizer:
    def __init__(self, model: str | None = None):
        import anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = model or settings.liaison_model

    def rephrase(self, text: str, lang: str) -> str:
        msg = self.client.messages.create(model=self.model, max_tokens=120, messages=[{"role": "user", "content":
            PROMPT.format(text=text, lang="Spanish" if lang == "es" else "English")}])
        out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return out or text


def humanizer():
    if not settings.anthropic_api_key:
        return None
    try:
        return Humanizer()
    except Exception:  # noqa: BLE001
        return None
