"""Optional Claude assist for the liaison: turns one utterance into one field value when the rule-based
Spanish parser cannot. It never decides what to say, never computes dates, and only sees the utterance (already
past the keyword check and number redaction) plus the field's type. Enabled when ANTHROPIC_API_KEY is set."""

from __future__ import annotations

import json
from typing import Any

from ..config import settings

PROMPT = """Extract the applicant's answer for ONE form field from a Spanish utterance.
Field: {key} ({label}); type: {type}; allowed options: {options}.
Return ONLY JSON: {{"value": <value or null>, "understood": true|false}}.
Dates: ISO YYYY-MM-DD, or YYYY-MM if only month and year were said. Never compute or infer a date that was not said.
yes_no_unsure: "yes" | "no" | "not_sure". bool: true/false. int: a number. Names: as said, capitalized.
Utterance: {text}"""


class ClaudeExtractor:
    def __init__(self, model: str | None = None):
        import anthropic
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = model or settings.liaison_model

    def extract(self, key: str, d: dict[str, Any], text: str) -> tuple[Any, bool]:
        msg = self.client.messages.create(model=self.model, max_tokens=200, messages=[{"role": "user", "content":
            PROMPT.format(key=key, label=d.get("label_en", key), type=d.get("type", "string"),
                          options=d.get("options", "any"), text=text)}])
        raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        out = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        return out.get("value"), bool(out.get("understood")) and out.get("value") is not None


def extractor():
    if not settings.anthropic_api_key:
        return None
    try:
        return ClaudeExtractor()
    except Exception:  # noqa: BLE001
        return None
