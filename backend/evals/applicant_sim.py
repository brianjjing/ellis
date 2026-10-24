"""Simulated applicant for end-to-end flow evals: answers whatever the liaison is actually asking, in Spanish,
from the synthetic case script, with planted behaviors (hedges, barge-in corrections, disclosures)."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from ellis.rules.engine import MONTHS_ES
from ellis.services import catalog

ENUM_SAY = {
    "married": "Casada", "single": "Soltera", "divorced": "Divorciada", "widowed": "Viuda",
    "lpr": "Es residente permanente", "us_citizen": "Es ciudadano estadounidense", "other": "Otra cosa",
    "online": "En línea", "paper": "En papel", "biological": "Biológico", "adopted": "Adoptado",
    "stepchild": "Hijastro",
}


def say_value(field: str, value: Any) -> str:
    d = catalog.field_def(field) or {}
    t = d.get("type")
    if isinstance(value, bool):
        return "Sí" if value else "No"
    if value is None:
        return "No"
    if t in ("date", "date_or_present") and isinstance(value, str) and len(value) >= 7:
        y, m = int(value[:4]), int(value[5:7])
        if len(value) == 10:
            return f"El {int(value[8:10])} de {MONTHS_ES[m - 1]} de {y}"
        return f"En {MONTHS_ES[m - 1]} de {y}"
    if t == "yes_no_unsure":
        return {"yes": "Sí", "no": "No", "not_sure": "No estoy segura"}[value]
    if t == "enum":
        return ENUM_SAY.get(value, str(value))
    if t == "string_list":
        return ", ".join(value) if value else "No, ninguno"
    if t == "optional_name":
        return f"Sí: {value}" if value else "No"
    if t == "int":
        return str(value)
    if t == "us_state":
        return {"CA": "California"}.get(value, value)
    if t == "benefit":
        return value or "No"
    return str(value)


class SimApplicant:
    """`overrides[field]` = utterance, or a list consumed in order (e.g. first answer, then read-back answer)."""

    def __init__(self, answers: dict[str, Any], overrides: dict[str, Any] | None = None,
                 readback_overrides: dict[str, Any] | None = None, secure: Callable[[str, Any], None] | None = None,
                 biographics: Callable[[dict], None] | None = None, upload: Callable[[str], None] | None = None):
        self.answers = answers
        self.overrides = {k: (list(v) if isinstance(v, list) else [v]) for k, v in (overrides or {}).items()}
        self.rb = {k: (list(v) if isinstance(v, list) else [v]) for k, v in (readback_overrides or {}).items()}
        self.secure = secure
        self.biographics = biographics
        self.upload = upload
        self.log: list[str] = []

    def respond(self, pending: dict | None, last_kind: str | None) -> tuple[str, str | None, str | None]:
        """Return (utterance, interrupted_field, interrupted_word)."""
        if pending is None:
            return "Sí, sigamos.", None, None
        kind, field = pending.get("kind"), pending.get("field")
        if kind in ("read_back", "correction"):
            q = self.rb.get(field)
            if q:
                u = q.pop(0)
                if isinstance(u, tuple):  # (utterance, barge-in word)
                    return u[0], field, u[1]
                return u, None, None
            if kind == "correction":
                return say_value(field, self.answers.get(field)), None, None
            return "Sí, es correcto.", None, None
        if kind == "secure_wait":
            if field in self.answers and self.secure:
                self.secure(field, self.answers[field])
            return "Listo, ya lo escribí.", None, None
        q = self.overrides.get(field)
        if q:
            return q.pop(0), None, None
        if field in self.answers:
            return say_value(field, self.answers[field]), None, None
        if field and field.startswith("background.detail.other_citations"):
            return "No, ninguna otra.", None, None
        if field and field.startswith("employment.gap"):
            return "Estaba entre trabajos.", None, None
        if field and field.startswith("followup."):
            return "Sí, ya tengo el papel.", None, None
        if field and field.endswith(".another"):
            return "No, ningún otro.", None, None
        return "No sé.", None, None


def run_conversation(liaison, sim: SimApplicant, max_turns: int = 200, on_turn=None,
                     printer=None) -> list[tuple[str, str]]:
    """Drive a liaison session to its natural close. Returns the transcript [(speaker, text)]."""
    out: list[tuple[str, str]] = []
    lines = liaison.start()
    for ln in lines:
        out.append(("ellis", ln.text))
        if printer:
            printer("ellis", ln)
    for _ in range(max_turns):
        if liaison.ended:
            break
        if liaison.mode == "consent":
            u, f, w = "Sí, de acuerdo.", None, None
        elif liaison.mode == "third_party_check":
            u, f, w = sim.overrides.pop("__third_party__", ["No, estoy sola."])[0], None, None
        elif liaison.mode == "stopped":
            q = sim.overrides.get("__after_stop__")
            u, f, w = (q.pop(0) if q else "Está bien, sigamos."), None, None
        else:
            u, f, w = sim.respond(liaison.pending, None)
        out.append(("usted", u))
        if printer:
            printer("usted", u, w)
        lines = liaison.handle(u, f, w)
        for ln in lines:
            if ln.kind == "biographics_request" and sim.biographics:
                sim.biographics({k: v for k, v in sim.answers.items()
                                 if k in ("sex", "height", "weight", "eye_color", "hair_color", "ethnicity", "race")})
            if ln.kind == "upload_request" and sim.upload:
                sim.upload(ln.text)
            out.append(("ellis", ln.text))
            if printer:
                printer("ellis", ln)
        if on_turn:
            on_turn()
    return out
