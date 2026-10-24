"""The liaison's turn engine: one question per turn, records every answer in the same turn, never waits on staff.

Channel-agnostic: the in-house voice gateway (Cartesia Ink + Sonic), the text fallback, the Line agent wrapper
and the evals all drive the same `Liaison`. Control flow is deterministic (briefing queue → fallback queue,
read-back protocol, stop-now, secure entry). Parsing is rule-based Spanish; when ANTHROPIC_API_KEY is set,
Claude assists only in turning an utterance into a field value (never in deciding what to say about the case).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field as dc_field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..services import catalog
from ..services.keywords import fold
from . import spanish

log = logging.getLogger("ellis.liaison")

ACKS = ["Gracias.", "Muy bien.", "Gracias.", "Entendido."]


@lru_cache
def scripts() -> dict[str, Any]:
    return yaml.safe_load((Path(__file__).parent / "scripts_es.yaml").read_text(encoding="utf-8"))


def script(key: str, **kw) -> "Say":
    sc = scripts()[key]
    return Say(sc["text"].format(**kw), locked=bool(sc.get("locked")), kind=key)


@dataclass
class Say:
    text: str
    locked: bool = False
    kind: str = "say"
    field: str | None = None  # read-back field: a barge-in during this line maps to this field
    end_call: bool = False
    meta: dict = dc_field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"text": self.text, "locked": self.locked, "kind": self.kind, "field": self.field,
                "end_call": self.end_call, **({"meta": self.meta} if self.meta else {})}


class Liaison:
    def __init__(self, client, today: date | None = None, channel: str = "voice", llm=None, rng_seed: int = 7):
        self.c = client
        self.today = today or date.today()
        self.channel = channel
        self.llm = llm
        self.mode = "start"
        self.pending: dict[str, Any] | None = None
        self.readback: dict[str, Any] | None = None
        self.briefing_version = 0
        self.attempts: dict[str, int] = {}
        self.skip: set[str] = set()
        self.local_queue: list[dict[str, Any]] = []
        self.stop_count = 0
        self.consent_prompts = 0
        self.third_party = False
        self.cfg: dict[str, Any] = {}
        self.ended = False
        self.sections_done_start: set[str] = set()
        self.last_question: list[Say] = []
        self._rng = random.Random(rng_seed)
        self.facts: dict[str, Any] = {}
        self.current_section: str | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> list[Say]:
        self.cfg = self.c.session_start(self.channel)
        b = self.c.get_briefing()
        self.sections_done_start = {p["section"] for p in b.get("progress", []) if p["state"] == "done"}
        if not self.cfg.get("consent_given"):
            lines = [script("disclosure", clinic_name=self.cfg.get("clinic_name", "su clínica"))]
            if self.cfg.get("patient_mode"):
                lines.append(script("third_party_check"))
                self.mode = "third_party_check"
            else:
                self.mode = "consent"
            return self._said(lines)
        self.mode = "queue"
        hello = Say(f"Hola, {self.cfg.get('first_name', '')}. Soy Ellis. Seguimos donde nos quedamos.")
        return self._said([hello] + self.next_question())

    def _said(self, lines: list[Say]) -> list[Say]:
        for ln in lines:
            try:
                self.c.liaison_said(ln.text, ln.locked)
            except Exception:  # noqa: BLE001 - captions are best-effort
                log.exception("liaison_said failed")
        return lines

    # ------------------------------------------------------------ turns

    def handle(self, text: str, interrupted_field: str | None = None,
               interrupted_at_word: str | None = None) -> list[Say]:
        if self.ended:
            return []
        text = (text or "").strip()
        if not text:
            return []
        t = self.c.applicant_turn(text)
        if t.get("stop"):
            return self._said(self._on_stop(t))
        if t.get("redacted"):
            return self._said(self._secure_repeat())
        uid = t.get("utterance_id")
        if self.mode == "third_party_check":
            return self._said(self._third_party(text))
        if self.mode == "consent":
            return self._said(self._consent(text, uid))
        if self.mode == "closed":
            return []
        if spanish.wants_to_stop(text):
            return self._said(self.close())
        if self.mode == "stopped":
            return self._said(self._after_stop(text))
        if spanish.is_advice_question(text) and not (self.pending and self.pending["kind"] == "read_back"
                                                     and spanish.yes_no(text) is not None):
            return self._said(self._advice() + self.last_question)
        if self.pending is None:
            return self._said(self.next_question())
        kind = self.pending["kind"]
        if kind == "read_back" or kind == "correction":
            return self._said(self._readback_answer(text, uid, interrupted_at_word))
        if kind == "secure_wait":
            self.pending = None
            return self._said(self.next_question())
        return self._said(self._answer(text, uid))

    def silence(self, seconds: float) -> list[Say]:
        if self.ended or self.mode in ("start",):
            return []
        a, b, c = self.cfg.get("silence_thresholds_s", [8, 20, 60])
        if seconds >= c:
            return self._said([script("another_day")])
        if seconds >= b:
            return self._said(self.last_question or [script("take_your_time")])
        if seconds >= a:
            return self._said([script("take_your_time")])
        return []

    # ------------------------------------------------------------ consent

    def _third_party(self, text: str) -> list[Say]:
        rel = spanish.third_party_relation(text)
        yn = spanish.yes_no(text)
        self.mode = "consent"
        if rel or yn is True:
            self.third_party = True
            self.c.third_party(True, rel)
            name = self.cfg.get("first_name", "")
            return [script("third_party_welcome", name=f"la señora {name}" if rel in ("daughter", "son", "granddaughter",
                                                                                      "grandson") else name,
                           name_vocative=f"Señora {name}" if rel in ("daughter", "son") else name)]
        return [Say("Gracias. ¿Está de acuerdo en continuar?")]

    def _consent(self, text: str, uid: str | None) -> list[Say]:
        yn = spanish.yes_no(text)
        if yn is True:
            res = self.c.record_fact("consent", True, utterance_id=uid)
            if not res.get("saved"):
                return [script("tool_failure")]
            self.mode = "queue"
            return [script("consent_thanks")] + self.next_question()
        if yn is False:
            self.c.record_fact("consent", False, utterance_id=uid)
            self.mode = "closed"
            self.ended = True
            self.c.session_end()
            out = script("consent_declined")
            out.end_call = True
            return [out]
        self.consent_prompts += 1
        if self.consent_prompts >= 2:
            self.mode = "closed"
            self.ended = True
            self.c.session_end()
            out = script("consent_declined")
            out.end_call = True
            return [out]
        return [Say("Perdón. ¿Está de acuerdo en continuar? Puede decir sí o no.")]

    # ------------------------------------------------------------ stop-now

    def _on_stop(self, t: dict) -> list[Say]:
        self.stop_count += 1
        if self.pending and self.pending.get("field"):
            self.skip.add(self.pending["field"])  # interrupted field returns to the queue unconfirmed, not now
        self.pending = None
        self.readback = None
        self.mode = "stopped"
        if t.get("new_flag", True) and self.stop_count == 1:
            self.c.stop_spoken()
            return [script("stop")]
        if t.get("new_flag"):
            self.c.stop_spoken()
            return [script("stop")]
        if self.stop_count <= 3:
            return [script("stop_repeat")]
        return [script("stop_offer_end")]

    def _after_stop(self, text: str) -> list[Say]:
        if spanish.is_advice_question(text):
            self.stop_count += 1
            return [script("stop_repeat") if self.stop_count <= 3 else script("stop_offer_end")]
        yn = spanish.yes_no(text)
        if yn is False:
            return self.close()
        self.mode = "queue"
        return self.next_question()

    def _secure_repeat(self) -> list[Say]:
        field = self.pending.get("field") if self.pending else None
        if not field or not (catalog.field_def(field) or {}).get("capture", "").startswith("S"):
            field = "a_number"
        self.c.request_secure_entry(field)
        self.pending = {"kind": "secure_wait", "field": field}
        return [script("secure_entry_repeat")]

    def _advice(self) -> list[Say]:
        b = self.c.get_briefing()
        explain = ((b.get("derived") or {}).get("explain") or {})
        if "exemptions" in explain:
            return [script("will_i_qualify", rule_explain=explain["exemptions"]["text_es"])]
        return [script("cant_advise")]

    # ------------------------------------------------------------ queue

    def _item_key(self, it: dict) -> str:
        return f"{it.get('kind')}:{it.get('field') or it.get('document_type') or it.get('section')}"

    def next_question(self, _depth: int = 0) -> list[Say]:
        if _depth > 6:
            return []
        b = self.c.get_briefing()
        self.briefing_version = b.get("version", 0)
        self.facts = dict(b.get("facts") or {})
        fallback = b.get("fallback", [])
        queue = list(b.get("queue", []))
        # Briefing items naming a field come first; then finish the current section; then section-level items.
        explicit = [it for it in queue if it.get("field")]
        sectional = [it for it in queue if not it.get("field")]
        in_section = [it for it in fallback if self.current_section and it.get("section") == self.current_section
                      and it.get("kind") != "read_back"]
        in_section += [it for it in fallback if self.current_section and it.get("section") == self.current_section
                       and it.get("kind") == "read_back"]
        items = list(self.local_queue) + explicit + in_section + sectional + fallback
        out: list[Say] = []
        for it in items:
            key = self._item_key(it)
            if key in self.skip or (it.get("field") and it["field"] in self.skip):
                continue
            if it.get("field") == "consent":
                continue
            kind = it.get("kind")
            if kind == "ask" and not it.get("field"):
                sec = it.get("section")
                sub = next((f for f in fallback if f.get("section") == sec and self._item_key(f) not in self.skip
                            and f.get("field") not in self.skip), None)
                if sub is None:
                    continue
                it = sub
                kind = it.get("kind")
            if it in self.local_queue:
                self.local_queue.remove(it)
            if kind == "ask":
                return out + self._ask(it)
            if kind == "read_back":
                rb = self._start_readback(it)
                if rb:
                    return out + rb
                self.skip.add(it["field"])
                continue
            if kind == "request_secure_entry":
                self.skip.add(key)
                self.c.request_secure_entry(it["field"])
                self.pending = {"kind": "secure_wait", "field": it["field"]}
                line = script("secure_entry", label=catalog.label_es(it["field"]).lower())
                self.last_question = [line]
                return out + [line]
            if kind == "request_upload":
                self.skip.add(key)
                self.c.request_upload(it.get("document_type", "other"))
                from ..extraction.schemas import LABELS_ES
                out.append(script("upload_request", document_label=LABELS_ES.get(it.get("document_type"), "documento")))
                continue  # the liaison never waits for an upload
            if kind == "request_biographics":
                self.skip.add(key)
                self.c.request_biographics()
                out.append(script("biographics_request"))
                continue
            if kind == "say" and it.get("text_es"):
                self.skip.add(key)
                out.append(Say(it["text_es"]))
                continue
        if out:
            return out
        return self.close(all_done=not fallback)

    def _ask(self, it: dict) -> list[Say]:
        f = it["field"]
        self.pending = {"kind": "ask", **it}
        d = catalog.field_def(f) or {}
        self.current_section = d.get("section", self.current_section)
        q = it.get("question_es") or catalog.question_for(f)
        lines = []
        if d.get("official"):
            lines.append(Say(q, kind="official_question", meta={"text_en": d.get("question_en"), "field": f}))
        else:
            lines.append(Say(q, kind="question", meta={"field": f}))
        self.last_question = lines
        return lines

    def _start_readback(self, it: dict) -> list[Say] | None:
        f = it["field"]
        rb = self.c.read_back(f, it.get("read_value"), self.briefing_version)
        if rb.get("error"):
            return None
        self.readback = rb
        self.pending = {"kind": "read_back", **it}
        label = readback_label(f)
        if self.third_party:
            line = script("readback_third_party", name_vocative=self.cfg.get("first_name", ""), label=label,
                          spoken=rb["spoken"])
        elif rb.get("source") == "document":
            from ..extraction.schemas import LABELS_ES
            doc = "documento"
            if f in ("lpr_since", "dob", "name.given", "name.family", "country_of_birth"):
                doc = LABELS_ES["green_card"]
            if f == "nationality":
                doc = LABELS_ES["passport"]
            line = script("readback_document", document_label=doc, label=label, spoken=rb["spoken"])
            d = catalog.field_def(f) or {}
            if d.get("rb_doc_es"):
                line.text = f"Su {doc} dice {d['rb_doc_es']} {rb['spoken']}. ¿Es correcto?"
        else:
            line = script("readback_applicant", label=label, spoken=rb["spoken"])
        line.kind = "readback"
        line.field = f
        self.last_question = [line]
        return [line]

    # ------------------------------------------------------------ answers

    def _parse(self, f: str, text: str, ref: str | None = None) -> tuple[Any, bool]:
        d = catalog.field_def(f) or {}
        ftype = d.get("type", "string")
        v, ok = spanish.parse_value(f, ftype, text, ref=ref, today=self.today)
        if not ok and self.llm is not None:
            try:
                v, ok = self.llm.extract(f, d, text)
            except Exception:  # noqa: BLE001
                log.exception("llm extract failed")
        return v, ok

    def _answer(self, text: str, uid: str | None) -> list[Say]:
        it = self.pending or {}
        f = it["field"]
        d = catalog.field_def(f) or {}
        hedge = spanish.has_hedge(text)
        value, ok = self._parse(f, text, ref=self._ref_for_text(f))
        if value == "__YES__":
            self.pending = {"kind": "ask", "field": f, "question_es": d.get("followup_es", "¿Cuál?")}
            q = Say(self.pending["question_es"])
            self.last_question = [q]
            return [q]
        if not ok:
            n = self.attempts.get(f, 0) + 1
            self.attempts[f] = n
            if n >= 2:
                self.skip.add(f)
                self.pending = None
                return [script("not_understood"), Say("Lo vemos más adelante.")] + self.next_question()
            return [script("not_understood")] + self.last_question
        res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid)
        if res.get("stopped"):
            self.c.stop_spoken()
            self.mode = "stopped"
            self.pending = None
            return [script("stop")]
        if not res.get("saved"):
            err = (res.get("error") or {}).get("code")
            if err == "invalid_value":
                self.attempts[f] = self.attempts.get(f, 0) + 1
                if self.attempts[f] >= 2:
                    self.skip.add(f)
                    self.pending = None
                    return [script("not_understood")] + self.next_question()
                return [script("not_understood")] + self.last_question
            if err == "deferred_to_professional":
                self.skip.add(f)
                self.pending = None
                return self.next_question()
            return [script("tool_failure")]
        self.pending = None
        lines = self._react(res, f)
        lines += self._opportunistic(f, value, text, uid)
        if not lines:
            lines = [Say(self._rng.choice(ACKS))] if self._rng.random() < 0.35 else []
        return lines + self.next_question()

    def _ref_for_text(self, f: str) -> str | None:
        """A spoken return date without a year takes it from the departure ("el tres de marzo del..." )."""
        m = catalog.LIST_RE.match(f)
        if m and m["list"] == "trips" and m["sub"] == "return":
            return self.facts.get(f"trips[{m['i']}].departure")
        return None

    def _remember(self, f: str, v: Any) -> None:
        self.facts[f] = v

    def _react(self, res: dict, f: str) -> list[Say]:
        fact = res.get("fact") or {}
        if fact:
            self._remember(f, fact.get("value"))
        cats = {fl.get("category") for fl in res.get("flags", []) if fl.get("speed") != "stop_now"}
        lines = []
        if cats & {"absence_gt_180", "absence_gte_365"}:
            lines.append(script("flag_absence"))
        elif cats & {"citation", "taxes", "oath_answer", "selective_service", "medical_exception_question"}:
            lines.append(script("flag_card"))
            if "citation" in cats:
                for k, q in (("background.detail.citation_year", "¿En qué año fue?"),
                             ("background.detail.citation_county", "¿En qué condado fue?"),
                             ("background.detail.citation_paid", "¿Ya la pagó, o todavía no?")):
                    self.local_queue.append({"kind": "ask", "field": k, "question_es": q, "reason": "suggested_followup"})
        elif cats & {"name_mismatch", "presence_short", "other_path", "document_conflict"}:
            lines.append(script("flag_neutral"))
        err = (res.get("derived") or {}).get("error")
        if err and err != getattr(self, "_last_rules_error", None):
            lines.append(script("rules_later"))
        self._last_rules_error = err
        return lines

    def _opportunistic(self, f: str, value: Any, text: str, uid: str | None) -> list[Say]:
        """Capture extra facts volunteered in the same answer (one utterance, several fields)."""
        m = catalog.LIST_RE.match(f)
        idx = None
        if f == "trips.any" and value is True:
            idx = 0
        elif m and m["list"] == "trips" and m["sub"] == "another" and value is True:
            idx = int(m["i"]) + 1
        elif m and m["list"] == "trips" and m["sub"] == "departure":
            idx = int(m["i"])
            self._remember(f, value)
        if idx is None:
            return []
        hedge = spanish.has_hedge(text)
        if f == "trips.any" or (m and m["sub"] == "another"):
            dep, prec = spanish.parse_date(text, today=self.today)
            if dep:
                r = self.c.record_fact(f"trips[{idx}].departure", dep, hedge=hedge, utterance_id=uid)
                if r.get("saved"):
                    self._remember(f"trips[{idx}].departure", dep)
        country = spanish.parse_country(text)
        if country:
            self.c.record_fact(f"trips[{idx}].countries", country, utterance_id=uid)
        reason = spanish.parse_trip_reason(text)
        if reason:
            self.c.record_fact(f"trips[{idx}].reason", reason, utterance_id=uid)
        return []

    def _readback_answer(self, text: str, uid: str | None, word: str | None) -> list[Say]:
        it = self.pending or {}
        f = it["field"]
        rb = self.readback or {}
        read_val = rb.get("value")
        yn = spanish.yes_no(text)
        hedge = spanish.has_hedge(text)
        ftype = (catalog.field_def(f) or {}).get("type")
        rest = spanish.strip_yes_no(text)
        ref = read_val if isinstance(read_val, str) else None
        if it["kind"] == "correction" or yn is None:
            value, ok = self._parse(f, text, ref=ref)
        elif yn is False or ftype in ("date", "date_or_present"):
            value, ok = self._parse(f, rest, ref=ref) if rest else (None, False)
        else:
            value, ok = None, False  # "sí, así es" confirms; it is not a new value
        differs = ok and value is not None and fold(str(value)) != fold(str(read_val))
        if ftype == "bool" and yn is not None:
            differs = isinstance(read_val, bool) and yn != read_val
            value = yn
        if it["kind"] == "correction":
            if ok and value is not None:
                res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid, interrupted_at_word=word,
                                         is_correction=True)
                return self._after_readback(res, f, corrected=True)
            return [script("not_understood"), Say(f"¿Cuál es {catalog.label_es(f).lower()} correcto?")]
        if spanish.yes_no_unsure(text) == "not_sure" and not differs:
            self.skip.add(f)
            self.pending = None
            self.readback = None
            return [Say("Está bien, lo dejamos así por ahora.")] + self.next_question()
        if differs or (word and ok and value is not None):
            res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid, interrupted_at_word=word)
            return self._after_readback(res, f, corrected=True)
        if yn is True:
            if hedge:
                self.skip.add(f)
                self.pending = None
                return [Say("Está bien, lo dejamos así por ahora.")] + self.next_question()
            res = self.c.record_fact(f, read_val, utterance_id=uid)
            return self._after_readback(res, f, corrected=False)
        if yn is False:
            self.pending = {"kind": "correction", "field": f}
            q = Say(f"¿Cuál es {catalog.label_es(f).lower()} correcto?")
            self.last_question = [q]
            return [q]
        n = self.attempts.get("rb:" + f, 0) + 1
        self.attempts["rb:" + f] = n
        if n >= 2:
            self.skip.add(f)
            self.pending = None
            return [script("not_understood")] + self.next_question()
        return [script("not_understood")] + self.last_question

    def _after_readback(self, res: dict, f: str, corrected: bool) -> list[Say]:
        self.pending = None
        self.readback = None
        if not res.get("saved"):
            return [script("tool_failure")] + self.last_question
        fact = res.get("fact") or {}
        self._remember(f, fact.get("value"))
        lines: list[Say] = []
        if fact.get("status") == "disputed":
            lines.append(script("flag_neutral"))
        elif corrected:
            txt = f"Entendido: {res.get('spoken')}."
            if fact.get("matches_document"):
                txt += " Coincide con su documento." if f != "trips[0].return" and "trips[" not in f else \
                    " Coincide con su pasaporte."
            lines.append(Say(txt))
        else:
            der = res.get("derived") or {}
            if f == "lpr_since" and der.get("earliest_filing_spoken"):
                if der.get("window_open"):
                    lines.append(Say("Gracias. Según la regla, la ventana para presentar su solicitud ya está abierta; "
                                     "le explico más adelante qué falta."))
                else:
                    lines.append(Say(f"Gracias. Según la regla, puede presentar su solicitud desde "
                                     f"{der['earliest_filing_spoken']}."))
            else:
                lines.append(Say("Gracias."))
        lines += [ln for ln in self._react(res, f) if ln.kind != "flag_absence"]
        return lines + self.next_question()

    # ------------------------------------------------------------ close

    def close(self, all_done: bool = False) -> list[Say]:
        b = self.c.get_briefing()
        if all_done:
            line = script("session_close_all_done")
        else:
            close = b.get("session_close") or {}
            done = close.get("sections_done") or [p["label"].lower() for p in b.get("progress", [])
                                                   if p["state"] == "done" and p["section"] != "consent"]
            nxt = close.get("next_items") or (b.get("gaps") or [])[:3] or [
                p["label"].lower() for p in b.get("progress", []) if p["state"] in ("partial", "not_started")][:3]
            line = script("session_close", sections_done=_join(done) or "lo que pudimos",
                          next_items=_join(nxt) or "seguir con sus respuestas")
        line.end_call = True
        self.mode = "closed"
        self.ended = True
        self.c.session_end()
        return [line]


def readback_label(f: str) -> str:
    d = catalog.field_def(f) or {}
    if d.get("rb_es"):
        lbl = d["rb_es"]
    else:
        lbl = d.get("label_es", f).split(": ")[-1].lower()
        lbl = f"«{lbl}»"
    m = catalog.LIST_RE.match(f)
    if m and int(m["i"]) >= 0 and m["list"] in ("trips", "addresses", "employment", "children"):
        lbl += f" ({catalog.list_item_label(m['list'], int(m['i'])).lower()})" if m["list"] != "trips" or int(m["i"]) > 0 else ""
    return lbl


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " y " + items[-1]
