"""The logged-out guide: stateless. Answers come from the browser and go back to it; nothing is stored or logged."""

from __future__ import annotations

from datetime import date


from ..config import rule_config
from ..rules.engine import earliest_filing
from ..voice.english import parse_value, yes_no
from . import keywords

QUESTIONS = [("lpr_since", "When did you become a permanent resident? The date on your green card is fine."),
             ("married_to_citizen", "Are you married to a U.S. citizen?")]
STOP_REPLY = ("That's something to talk through with a clinic or attorney before you go further. I can't help with it "
              "here, but a clinic can, and it's confidential.")
MARRIED_NOTE = (" If you've been married to and living with a U.S. citizen for 3 years, you may qualify sooner; "
                "a clinic can confirm.")


def respond(messages: list[dict], answers: dict, today: date) -> dict:
    answers = dict(answers or {})
    last = next((m["text"] for m in reversed(messages) if m.get("who") == "you"), "")
    if last and keywords.stop_hit(last):
        return {"reply": STOP_REPLY, "answers": answers, "estimate": None, "stop": True}
    asked = next((k for k, _ in QUESTIONS if k not in answers), None)
    if last and asked == "lpr_since":
        v, ok = parse_value("lpr_since", "date", last, today=today)
        if ok and len(str(v)) >= 7:  # a year alone isn't enough for an estimate
            answers["lpr_since"] = str(v)
    elif last and asked == "married_to_citizen":
        v = yes_no(last)
        if v is not None:
            answers["married_to_citizen"] = v
    # ponytail: scripted guide only; a Claude-backed guide (prompts/guest_guide.md) can replace this reply later.
    nxt = next((q for k, q in QUESTIONS if k not in answers), None)
    estimate = None
    if answers.get("lpr_since"):
        d = answers["lpr_since"]
        when = earliest_filing(date.fromisoformat(d + "-01" if len(d) == 7 else d), rule_config())
        estimate = {"earliest_filing": when.isoformat(), "window_open": when <= today}
    reply = ""
    if estimate and asked == "lpr_since" and "lpr_since" in answers:
        reply = (f"Based on that, the earliest you could file is {estimate['earliest_filing']}. " if not estimate["window_open"]
                 else "Based on that, you may be able to file now. ")
    reply += nxt or "That's what I need for a first check. Create a free account to save this and start your N-400."
    if answers.get("married_to_citizen") is True:
        reply += MARRIED_NOTE
    return {"reply": reply, "answers": answers, "estimate": estimate, "stop": False}
