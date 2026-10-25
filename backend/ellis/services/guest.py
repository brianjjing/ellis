"""The logged-out guide: stateless. Answers come from the browser and go back to it; nothing is stored or logged.

General questions are answered from prompts/guest_faq.md. The two eligibility questions are asked only
after the visitor opts in. With ANTHROPIC_API_KEY set, a model may phrase the answer; it may not invent one.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from ..config import PROMPTS_DIR, rule_config, settings
from ..rules.engine import earliest_filing
from ..voice.english import parse_value, yes_no
from . import keywords

STOP_REPLY = ("That's something to talk through with a clinic or attorney before you go further. I can't help with it "
              "here, but a clinic can, and it's confidential.")
OFFER = ("Want me to check where you stand? I'll ask 2 questions. Your answers stay in this browser until you "
         "make an account.")
OFFER_ES = ("¿Quiere que vea dónde está? Le haré 2 preguntas. Sus respuestas se quedan en este navegador hasta "
            "que cree una cuenta.")
LPR_Q = "When did you become a permanent resident? You can find it on your green card, next to 'Resident since.'"
LPR_Q_ES = "¿Cuándo se hizo residente permanente? Lo encuentra en su tarjeta de residente, junto a 'Residente desde.'"
MARRIED_Q = "Are you married to a U.S. citizen?"
MARRIED_Q_ES = "¿Está casado o casada con un ciudadano de los Estados Unidos?"
MARRIED_NOTE = " Your clinic will review whether a shorter wait applies."
MARRIED_NOTE_ES = " Su clínica revisará si aplica una espera más corta."
ACCOUNT = "That's what I need for a first check. Create a free account to save this and start your N-400."
ACCOUNT_ES = "Con eso basta para una primera revisión. Cree una cuenta gratis para guardar esto y empezar su N-400."
DECLINE = "Okay. You can ask me about the process whenever you want."
DECLINE_ES = "Está bien. Puede preguntarme sobre el proceso cuando quiera."
CONFUSED_REPLY = "I don't know that. Ellis doesn't already know it; I'm asking you."
CONFUSED_REPLY_ES = "No lo sé. Ellis no lo sabe de antemano; se lo estoy preguntando."
OPENING = ("I help people get ready to apply for U.S. citizenship. Ask me how applying works, what to have ready, "
           "or what the interview is.")
OPENING_ES = ("Ayudo a las personas a prepararse para solicitar la ciudadanía. Pregúnteme cómo funciona, qué tener "
              "listo, o qué es la entrevista.")

_CONFUSED = (
    "how do you know", "how would you know", "how did you know", "what do you mean", "i don't understand",
    "i am confused", "im confused", "that doesn't make sense", "you don't know",
    "como sabes", "cómo sabes", "como lo sabes", "no entiendo",
)


def model_configured() -> bool:
    return bool(settings.anthropic_api_key)


@lru_cache
def faq_entries() -> tuple[dict, ...]:
    text = (PROMPTS_DIR / "guest_faq.md").read_text()
    entries = []
    for block in re.split(r"\n(?=## )", text):
        if not block.startswith("## "):
            continue
        lines = block.splitlines()
        key = lines[0][3:].strip()
        keywords_line: list[str] = []
        body = {"en": [], "es": []}
        lang = "en"
        for ln in lines[1:]:
            if ln.lower().startswith("keywords:"):
                keywords_line = [k.strip() for k in ln.split(":", 1)[1].split(",") if k.strip()]
            elif ln.startswith("en:"):
                lang = "en"
                body["en"].append(ln[3:].strip())
            elif ln.startswith("es:"):
                lang = "es"
                body["es"].append(ln[3:].strip())
            elif ln.strip():
                body[lang].append(ln.strip())
        entries.append({"key": key, "keywords": keywords_line,
                        "en": " ".join(body["en"]), "es": " ".join(body["es"]) or " ".join(body["en"])})
    return tuple(entries)


def faq_text() -> str:
    return (PROMPTS_DIR / "guest_faq.md").read_text()


def _lang(language: str) -> str:
    return "es" if (language or "en").lower().startswith("es") else "en"


def _offer(lang: str) -> str:
    return OFFER_ES if lang == "es" else OFFER


def _confused(text: str) -> bool:
    f = keywords.fold(text)
    return any(keywords.fold(p) in f for p in _CONFUSED)


def _short(text: str, limit: int = 8) -> bool:
    return len(keywords.fold(text).split()) <= limit


def _match_faq(text: str) -> dict | None:
    folded = keywords.fold(text)
    best, best_len = None, 0
    for entry in faq_entries():
        for kw in entry["keywords"]:
            k = keywords.fold(kw)
            if k and k in folded and len(k) > best_len:
                best, best_len = entry, len(k)
    return best


def _prev_ellis(messages: list[dict]) -> str:
    return next((m.get("text") or "" for m in reversed(messages) if m.get("who") == "ellis"), "")


def _estimate(answers: dict, today: date) -> dict | None:
    raw = answers.get("lpr_since")
    if not raw:
        return None
    when = earliest_filing(date.fromisoformat(raw + "-01" if len(str(raw)) == 7 else str(raw)), rule_config())
    return {"earliest_filing": when.isoformat(), "window_open": when <= today}


def _filing_sentence(estimate: dict, lang: str) -> str:
    # The date comes from the rules engine. The sentence does not say the person qualifies.
    day = estimate["earliest_filing"]
    if lang == "es":
        return f"La fecha que usan las reglas es {day}. Su clínica revisará esto."
    return f"The date the rules use is {day}. Your clinic will review this."


def _not_same(reply: str, prev: str, last: str, lang: str) -> str:
    if not prev or reply.strip() != prev.strip():
        return reply
    if _confused(last):
        return CONFUSED_REPLY_ES if lang == "es" else CONFUSED_REPLY
    quoted = (last or "").strip()[:160]
    if lang == "es":
        return f"Sobre lo que acaba de decir ({quoted}): puedo responder desde la guía, o puede empezar las 2 preguntas."
    return f"About what you just said ({quoted}): I can answer from the guide, or you can start the 2 questions."


def _scripted(messages: list[dict], answers: dict, today: date, lang: str) -> tuple[str, dict, dict | None]:
    """Returns reply, updated answers, estimate. Caller handles stop and de-duplication."""
    answers = dict(answers or {})
    last = next((m["text"] for m in reversed(messages) if m.get("who") == "you"), "")
    offer = _offer(lang)
    confused = CONFUSED_REPLY_ES if lang == "es" else CONFUSED_REPLY

    def with_offer(body: str) -> str:
        if answers.get("check") == "no" or offer in body:
            return body
        return f"{body} {offer}"

    if answers.get("check") != "yes":
        if last and _short(last) and yes_no(last) is False:
            answers["check"] = "no"
            return (DECLINE_ES if lang == "es" else DECLINE), answers, None
        if last and _short(last) and yes_no(last) is True:
            answers["check"] = "yes"
            return (LPR_Q_ES if lang == "es" else LPR_Q), answers, None
        if last and _confused(last):
            return confused, answers, None
        hit = _match_faq(last) if last else None
        if hit:
            return with_offer(hit[lang]), answers, None
        if not last:
            return with_offer(OPENING_ES if lang == "es" else OPENING), answers, None
        quoted = last.strip()[:160]
        if lang == "es":
            body = f"Puedo explicar cómo funciona la solicitud, qué tener listo, o qué es la entrevista. Usted dijo: {quoted}."
        else:
            body = f"I can explain how applying works, what to have ready, or what the interview is. You said: {quoted}."
        return with_offer(body), answers, None

    # Opted in. Personal questions are allowed from here.
    stored_date = False
    if "lpr_since" not in answers:
        if last:
            value, ok = parse_value("lpr_since", "date", last, today=today)
            if ok and len(str(value)) >= 7:
                answers["lpr_since"] = str(value)
                stored_date = True
            elif _confused(last):
                return confused, answers, None
            else:
                hit = _match_faq(last)
                if hit:
                    remind = LPR_Q_ES if lang == "es" else LPR_Q
                    return f"{hit[lang]} {remind}", answers, None
                return (LPR_Q_ES if lang == "es" else LPR_Q), answers, None
        else:
            return (LPR_Q_ES if lang == "es" else LPR_Q), answers, None

    estimate = _estimate(answers, today)
    if "married_to_citizen" not in answers:
        # A date and a yes can share one sentence. The date wins; marriage is the next turn.
        if last and not stored_date and yes_no(last) is not None:
            answers["married_to_citizen"] = yes_no(last)
        else:
            filing = _filing_sentence(estimate, lang) + " " if estimate else ""
            return filing + (MARRIED_Q_ES if lang == "es" else MARRIED_Q), answers, estimate

    note = ""
    if answers.get("married_to_citizen") is True:
        note = MARRIED_NOTE_ES if lang == "es" else MARRIED_NOTE
    filing = (_filing_sentence(estimate, lang) + " ") if estimate else ""
    closing = ACCOUNT_ES if lang == "es" else ACCOUNT
    return filing + closing + note, answers, estimate


def complete_with_model(messages: list[dict], answers: dict, language: str) -> str:
    """One reply from the liaison's model. The caller still owns answers and the no-repeat rule."""
    import anthropic

    guide = (PROMPTS_DIR / "guest_guide.md").read_text()
    system = (guide.replace("{faq}", faq_text())
              .replace("{opted_in}", "yes" if answers.get("check") == "yes" else "no"))
    turns: list[dict] = []
    for m in messages:
        role = "assistant" if m.get("who") == "ellis" else "user"
        text = (m.get("text") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + text
        else:
            turns.append({"role": role, "content": text})
    if not turns or turns[0]["role"] != "user":
        opener = "(el visitante abrió el chat)" if _lang(language) == "es" else "(the visitor opened the chat)"
        turns.insert(0, {"role": "user", "content": opener})
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msg = client.messages.create(model=settings.conversation_model, max_tokens=400, system=system, messages=turns)
    return "".join(getattr(b, "text", "") for b in msg.content).strip()


def respond(messages: list[dict], answers: dict, today: date, language: str = "en") -> dict:
    answers = dict(answers or {})
    lang = _lang(language)
    last = next((m["text"] for m in reversed(messages) if m.get("who") == "you"), "")
    if last and keywords.stop_hit(last):
        return {"reply": STOP_REPLY, "answers": answers, "estimate": None, "stop": True}
    before = dict(answers)
    reply, answers, estimate = _scripted(messages, answers, today, lang)
    moved = answers != before
    if model_configured() and not moved:
        try:
            modeled = complete_with_model(messages, answers, language)
            if modeled:
                reply = modeled
        except Exception:
            pass
    reply = _not_same(reply, _prev_ellis(messages), last, lang)
    return {"reply": reply, "answers": answers, "estimate": estimate, "stop": False}
