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
from . import english, spanish
from .humanize import GENERIC_KINDS

log = logging.getLogger("ellis.liaison")

ACKS = {"es": ["Gracias.", "Muy bien.", "Gracias.", "Entendido."],
        "en": ["Thanks.", "Got it.", "Thank you.", "Understood."]}
NLU = {"es": spanish, "en": english}


@lru_cache
def scripts(lang: str = "es") -> dict[str, Any]:
    return yaml.safe_load((Path(__file__).parent / f"scripts_{lang}.yaml").read_text(encoding="utf-8"))


def script(key: str, lang: str = "es", **kw) -> "Say":
    sc = scripts(lang)[key]
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
    def __init__(self, client, today: date | None = None, channel: str = "voice", llm=None, humanizer=None,
                rng_seed: int = 7, language: str = "es"):
        self.c = client
        self.today = today or date.today()
        self.channel = channel
        self.llm = llm
        self.humanizer = humanizer
        self.language = language if language in NLU else "es"
        self.nlu = NLU[self.language]
        self.script = lambda key, **kw: script(key, lang=self.language, **kw)
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
        self._turn_uncertain = False
        self._llm_uncertain = False

    # ------------------------------------------------------------ lifecycle

    def start(self) -> list[Say]:
        self.cfg = self.c.session_start(self.channel)
        b = self.c.get_briefing()
        self.sections_done_start = {p["section"] for p in b.get("progress", []) if p["state"] == "done"}
        if not self.cfg.get("consent_given"):
            clinic_fallback = "your clinic" if self.language == "en" else "su clínica"
            lines = [self.script("disclosure", clinic_name=self.cfg.get("clinic_name", clinic_fallback))]
            if self.cfg.get("patient_mode"):
                lines.append(self.script("third_party_check"))
                self.mode = "third_party_check"
            else:
                self.mode = "consent"
            return self._said(lines)
        self.mode = "queue"
        hello = self.script("greeting_resume", first_name=self.cfg.get("first_name", ""))
        return self._said([hello] + self.next_question())

    def _said(self, lines: list[Say]) -> list[Say]:
        for ln in lines:
            # wording only, after the fact: hedge/flags/record_fact already happened before this line
            # was constructed, so rephrasing here can never change what was asked, recorded, or flagged.
            if self.humanizer is not None and not ln.locked and ln.kind in GENERIC_KINDS:
                try:
                    ln.text = self.humanizer.rephrase(ln.text, self.language)
                except Exception:  # noqa: BLE001 - never block the conversation on a rephrase failure
                    log.exception("humanize failed")
            try:
                self.c.liaison_said(ln.text, ln.locked)
            except Exception:  # noqa: BLE001 - captions are best-effort
                log.exception("liaison_said failed")
        return lines

    # ------------------------------------------------------------ turns

    def handle(self, text: str, interrupted_field: str | None = None,
               interrupted_at_word: str | None = None, turn_uncertain: bool = False) -> list[Say]:
        if self.ended:
            return []
        text = (text or "").strip()
        if not text:
            return []
        # Cartesia's turn model doesn't expose a confidence score, but when it flip-flopped between
        # turn.eager_end ("might be done") and turn.resume ("kept talking") before finally ending the
        # turn, that's the model itself being unsure — treat it the same as a hedge keyword match.
        self._turn_uncertain = turn_uncertain
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
        if self.nlu.wants_to_stop(text):
            return self._said(self.close())
        if self.mode == "stopped":
            return self._said(self._after_stop(text))
        if self.nlu.is_advice_question(text) and not (self.pending and self.pending["kind"] == "read_back"
                                                     and self.nlu.yes_no(text) is not None):
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
            return self._said([self.script("another_day")])
        if seconds >= b:
            return self._said(self.last_question or [self.script("take_your_time")])
        if seconds >= a:
            return self._said([self.script("take_your_time")])
        return []

    # ------------------------------------------------------------ consent

    def _third_party(self, text: str) -> list[Say]:
        rel = self.nlu.third_party_relation(text)
        yn = self.nlu.yes_no(text)
        self.mode = "consent"
        if rel or yn is True:
            self.third_party = True
            self.c.third_party(True, rel)
            name = self.cfg.get("first_name", "")
            if self.language == "es":
                honorific = rel in ("daughter", "son", "granddaughter", "grandson")
                disp_name = f"la señora {name}" if honorific else name
                vocative = f"Señora {name}" if rel in ("daughter", "son") else name
            else:
                disp_name = vocative = name
            return [self.script("third_party_welcome", name=disp_name, name_vocative=vocative)]
        return [self.script("third_party_fallback")]

    def _consent(self, text: str, uid: str | None) -> list[Say]:
        yn = self.nlu.yes_no(text)
        if yn is True:
            res = self.c.record_fact("consent", True, utterance_id=uid)
            if not res.get("saved"):
                return [self.script("tool_failure")]
            self.mode = "queue"
            return [self.script("consent_thanks")] + self.next_question()
        if yn is False:
            self.c.record_fact("consent", False, utterance_id=uid)
            self.mode = "closed"
            self.ended = True
            self.c.session_end()
            out = self.script("consent_declined")
            out.end_call = True
            return [out]
        self.consent_prompts += 1
        if self.consent_prompts >= 2:
            self.mode = "closed"
            self.ended = True
            self.c.session_end()
            out = self.script("consent_declined")
            out.end_call = True
            return [out]
        return [self.script("consent_retry")]

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
            return [self.script("stop")]
        if t.get("new_flag"):
            self.c.stop_spoken()
            return [self.script("stop")]
        if self.stop_count <= 3:
            return [self.script("stop_repeat")]
        return [self.script("stop_offer_end")]

    def _after_stop(self, text: str) -> list[Say]:
        if self.nlu.is_advice_question(text):
            self.stop_count += 1
            return [self.script("stop_repeat") if self.stop_count <= 3 else self.script("stop_offer_end")]
        yn = self.nlu.yes_no(text)
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
        return [self.script("secure_entry_repeat")]

    def _advice(self) -> list[Say]:
        b = self.c.get_briefing()
        explain = ((b.get("derived") or {}).get("explain") or {})
        if "exemptions" in explain:
            text_key = "text_en" if self.language == "en" else "text_es"
            return [self.script("will_i_qualify", rule_explain=explain["exemptions"].get(text_key, explain["exemptions"]["text_es"]))]
        return [self.script("cant_advise")]

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
            if key in self.skip or (it.get("field") and it["field"] in self.skip and it.get("kind") != "read_back"):
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
                if self._rb_key(it["field"]) in self.skip:
                    continue
                rb = self._start_readback(it)
                if rb:
                    return out + rb
                self._skip_rb(it["field"])
                continue
            if kind == "request_secure_entry":
                self.skip.add(key)
                self.c.request_secure_entry(it["field"])
                self.pending = {"kind": "secure_wait", "field": it["field"]}
                line = self.script("secure_entry", label=secure_label(it["field"], self.language))
                self.last_question = [line]
                return out + [line]
            if kind == "request_upload":
                self.skip.add(key)
                self.c.request_upload(it.get("document_type", "other"))
                from ..extraction.schemas import LABELS_EN, LABELS_ES
                text_key = f"text_{self.language}"
                if it.get(text_key):
                    out.append(Say(it[text_key], kind="upload_request"))
                elif it.get("text_es"):  # agent only provided Spanish; fall back rather than drop the line
                    out.append(Say(it["text_es"], kind="upload_request"))
                else:
                    labels = LABELS_EN if self.language == "en" else LABELS_ES
                    default_label = "document" if self.language == "en" else "documento"
                    out.append(self.script("upload_request",
                                      document_label=labels.get(it.get("document_type"), default_label)))
                continue  # the liaison never waits for an upload
            if kind == "request_biographics":
                self.skip.add(key)
                self.c.request_biographics()
                out.append(self.script("biographics_request"))
                continue
            if kind == "say" and it.get(f"text_{self.language}"):
                self.skip.add(key)
                out.append(Say(it[f"text_{self.language}"]))
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
        q = it.get(f"question_{self.language}") or catalog.question_for(f, lang=self.language)
        other_lang_text = d.get("question_es") if self.language == "en" else d.get("question_en")
        lines = []
        if d.get("official"):
            lines.append(Say(q, kind="official_question", meta={"text_en": other_lang_text, "field": f}))
        else:
            lines.append(Say(q, kind="question", meta={"field": f}))
        self.last_question = lines
        return lines

    def _start_readback(self, it: dict) -> list[Say] | None:
        f = it["field"]
        rb = self.c.read_back(f, it.get("read_value"), self.briefing_version, lang=self.language)
        if rb.get("error"):
            return None
        self.readback = rb
        self.pending = {"kind": "read_back", **it}
        label = readback_label(f, self.language)
        if self.third_party:
            line = self.script("readback_third_party", name_vocative=self.cfg.get("first_name", ""), label=label,
                          spoken=rb["spoken"])
        elif rb.get("source") == "document":
            from ..extraction.schemas import LABELS_EN, LABELS_ES
            labels = LABELS_EN if self.language == "en" else LABELS_ES
            doc = "document" if self.language == "en" else "documento"
            if f in ("lpr_since", "dob", "name.given", "name.family", "country_of_birth"):
                doc = labels["green_card"]
            if f == "nationality":
                doc = labels["passport"]
            line = self.script("readback_document", document_label=doc, label=label, spoken=rb["spoken"])
            d = catalog.field_def(f) or {}
            rb_doc = d.get("rb_doc_en") if self.language == "en" else d.get("rb_doc_es")
            if rb_doc:
                line.text = (f"Your {doc} says {rb_doc} {rb['spoken']}. Is that correct?" if self.language == "en"
                            else f"Su {doc} dice {rb_doc} {rb['spoken']}. ¿Es correcto?")
        else:
            line = self.script("readback_applicant", label=label, spoken=rb["spoken"])
        line.kind = "readback"
        line.field = f
        self.last_question = [line]
        return [line]

    # ------------------------------------------------------------ answers

    def _parse(self, f: str, text: str, ref: str | None = None) -> tuple[Any, bool]:
        self._llm_uncertain = False
        d = catalog.field_def(f) or {}
        ftype = d.get("type", "string")
        v, ok = self.nlu.parse_value(f, ftype, text, ref=ref, today=self.today)
        if not ok and self.llm is not None:
            try:
                v, ok, self._llm_uncertain = self.llm.extract(f, d, text)
            except Exception:  # noqa: BLE001
                log.exception("llm extract failed")
        return v, ok

    def _answer(self, text: str, uid: str | None) -> list[Say]:
        it = self.pending or {}
        f = it["field"]
        d = catalog.field_def(f) or {}
        hedge = self.nlu.has_hedge(text) or self._turn_uncertain
        value, ok = self._parse(f, text, ref=self._ref_for_text(f))
        hedge = hedge or self._llm_uncertain
        if value == "__YES__":
            followup_key = "followup_en" if self.language == "en" else "followup_es"
            default_followup = "Which one?" if self.language == "en" else "¿Cuál?"
            followup = d.get(followup_key, default_followup)
            self.pending = {"kind": "ask", "field": f, "question_es": followup}
            q = Say(followup)
            self.last_question = [q]
            return [q]
        if not ok:
            n = self.attempts.get(f, 0) + 1
            self.attempts[f] = n
            if n >= 2:
                self.skip.add(f)
                self.pending = None
                return [self.script("not_understood"), self.script("skip_for_now")] + self.next_question()
            return [self.script("not_understood")] + self.last_question
        res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid)
        if res.get("stopped"):
            self.c.stop_spoken()
            self.mode = "stopped"
            self.pending = None
            return [self.script("stop")]
        if not res.get("saved"):
            err = (res.get("error") or {}).get("code")
            if err == "invalid_value":
                self.attempts[f] = self.attempts.get(f, 0) + 1
                if self.attempts[f] >= 2:
                    self.skip.add(f)
                    self.pending = None
                    return [self.script("not_understood")] + self.next_question()
                return [self.script("not_understood")] + self.last_question
            if err == "deferred_to_professional":
                self.skip.add(f)
                self.pending = None
                return self.next_question()
            return [self.script("tool_failure")]
        self.pending = None
        lines = self._react(res, f)
        lines += self._opportunistic(f, value, text, uid)
        if not lines:
            lines = [Say(self._rng.choice(ACKS[self.language]))] if self._rng.random() < 0.35 else []
        return lines + self.next_question()

    def _ref_for_text(self, f: str) -> str | None:
        """A spoken return date without a year takes it from the departure ("el tres de marzo del..." )."""
        m = catalog.LIST_RE.match(f)
        if m and m["list"] == "trips" and m["sub"] == "return":
            return self.facts.get(f"trips[{m['i']}].departure")
        return None

    def _rb_key(self, f: str) -> str:
        return f"rb:{f}:{self.facts.get(f)}"

    def _skip_rb(self, f: str) -> None:
        """Skip reading back this value again in this session; a different value (e.g. a document's) still gets one."""
        self.skip.add(self._rb_key(f))

    def _remember(self, f: str, v: Any) -> None:
        self.facts[f] = v

    def _react(self, res: dict, f: str) -> list[Say]:
        fact = res.get("fact") or {}
        if fact:
            self._remember(f, fact.get("value"))
        cats = {fl.get("category") for fl in res.get("flags", []) if fl.get("speed") != "stop_now"}
        lines = []
        if cats & {"absence_gt_180", "absence_gte_365"}:
            lines.append(self.script("flag_absence"))
        elif cats & {"citation", "taxes", "oath_answer", "selective_service", "medical_exception_question"}:
            lines.append(self.script("flag_card"))
            if "citation" in cats:
                for k, script_key in (("background.detail.citation_year", "followup_citation_year"),
                                      ("background.detail.citation_county", "followup_citation_county"),
                                      ("background.detail.citation_paid", "followup_citation_paid")):
                    q = self.script(script_key).text
                    self.local_queue.append({"kind": "ask", "field": k, f"question_{self.language}": q,
                                            "reason": "suggested_followup"})
        elif cats & {"name_mismatch", "presence_short", "other_path", "document_conflict"}:
            lines.append(self.script("flag_neutral"))
        err = (res.get("derived") or {}).get("error")
        if err and err != getattr(self, "_last_rules_error", None):
            lines.append(self.script("rules_later"))
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
        hedge = self.nlu.has_hedge(text) or self._turn_uncertain
        if f == "trips.any" or (m and m["sub"] == "another"):
            dep, prec = self.nlu.parse_date(text, today=self.today)
            if dep:
                r = self.c.record_fact(f"trips[{idx}].departure", dep, hedge=hedge, utterance_id=uid)
                if r.get("saved"):
                    self._remember(f"trips[{idx}].departure", dep)
        country = self.nlu.parse_country(text)
        if country:
            self.c.record_fact(f"trips[{idx}].countries", country, utterance_id=uid)
        reason = self.nlu.parse_trip_reason(text)
        if reason:
            self.c.record_fact(f"trips[{idx}].reason", reason, utterance_id=uid)
        return []

    def _readback_answer(self, text: str, uid: str | None, word: str | None) -> list[Say]:
        it = self.pending or {}
        f = it["field"]
        rb = self.readback or {}
        read_val = rb.get("value")
        yn = self.nlu.yes_no(text)
        hedge = self.nlu.has_hedge(text) or self._turn_uncertain
        self._llm_uncertain = False  # only set if _parse() runs below; stale True from an earlier turn must not leak in
        ftype = (catalog.field_def(f) or {}).get("type")
        rest = self.nlu.strip_yes_no(text)
        ref = read_val if isinstance(read_val, str) else None
        if it["kind"] == "correction" or yn is None:
            value, ok = self._parse(f, text, ref=ref)
        elif yn is False or ftype in ("date", "date_or_present"):
            value, ok = self._parse(f, rest, ref=ref) if rest else (None, False)
        else:
            value, ok = None, False  # "sí, así es" confirms; it is not a new value
        hedge = hedge or self._llm_uncertain
        differs = ok and value is not None and fold(str(value)) != fold(str(read_val))
        if differs and yn is True and ftype in ("date", "date_or_present") and isinstance(read_val, str) \
                and len(str(value)) < len(read_val) and read_val.startswith(str(value)):
            differs = False  # "sí, 2020" agrees with 2020-06-02; it is a confirmation, not a less precise date
        if ftype == "bool" and yn is not None and isinstance(read_val, bool):
            # "sí" confirms what was read; "no" means the opposite value
            differs = yn is False
            value = (not read_val) if differs else read_val
            ok = True
        if it["kind"] == "correction":
            if ok and value is not None:
                res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid, interrupted_at_word=word,
                                         is_correction=True)
                return self._after_readback(res, f, corrected=True)
            return [self.script("not_understood"), self.script("ask_correct_value", label=readback_label(f, self.language))]
        if self.nlu.yes_no_unsure(text) == "not_sure" and not differs:
            self._skip_rb(f)
            self.pending = None
            self.readback = None
            return [self.script("leave_as_is")] + self.next_question()
        if differs or (word and ok and value is not None):
            res = self.c.record_fact(f, value, hedge=hedge, utterance_id=uid, interrupted_at_word=word)
            return self._after_readback(res, f, corrected=True)
        if yn is True:
            if hedge:
                self._skip_rb(f)
                self.pending = None
                return [self.script("leave_as_is")] + self.next_question()
            res = self.c.record_fact(f, read_val, utterance_id=uid)
            return self._after_readback(res, f, corrected=False)
        if yn is False:
            self.pending = {"kind": "correction", "field": f}
            q = self.script("ask_correct_value", label=readback_label(f, self.language))
            self.last_question = [q]
            return [q]
        n = self.attempts.get("rb:" + f, 0) + 1
        self.attempts["rb:" + f] = n
        if n >= 2:
            self._skip_rb(f)
            self.pending = None
            return [self.script("not_understood")] + self.next_question()
        return [self.script("not_understood")] + self.last_question

    def _after_readback(self, res: dict, f: str, corrected: bool) -> list[Say]:
        self.pending = None
        self.readback = None
        if not res.get("saved"):
            return [self.script("tool_failure")] + self.last_question
        fact = res.get("fact") or {}
        self._remember(f, fact.get("value"))
        lines: list[Say] = []
        if fact.get("status") == "disputed":
            lines.append(self.script("flag_neutral"))
        elif corrected:
            line = self.script("understood", spoken=res.get("spoken"))
            if fact.get("matches_document"):
                match = self.script("matches_passport" if (f == "trips[0].return" or "trips[" in f)
                                    else "matches_document")
                line.text += match.text
            lines.append(line)
        else:
            der = res.get("derived") or {}
            if f == "lpr_since" and der.get("earliest_filing_spoken"):
                if der.get("window_open"):
                    lines.append(self.script("window_open"))
                else:
                    spoken_key = "earliest_filing_spoken_en" if self.language == "en" else "earliest_filing_spoken"
                    lines.append(self.script("earliest_filing", date_spoken=der.get(spoken_key, der["earliest_filing_spoken"])))
            else:
                lines.append(self.script("thanks"))
        lines += [ln for ln in self._react(res, f) if ln.kind != "flag_absence"]
        return lines + self.next_question()

    # ------------------------------------------------------------ close

    def close(self, all_done: bool = False) -> list[Say]:
        b = self.c.get_briefing()
        if all_done:
            line = self.script("session_close_all_done")
        else:
            close = b.get("session_close") or {}
            done = close.get("sections_done") or [p["label"].lower() for p in b.get("progress", [])
                                                   if p["state"] == "done" and p["section"] != "consent"]
            nxt = close.get("next_items") or (b.get("gaps") or [])[:3] or [
                p["label"].lower() for p in b.get("progress", []) if p["state"] in ("partial", "not_started")][:3]
            done_fallback = "what we could" if self.language == "en" else "lo que pudimos"
            next_fallback = "continue with your answers" if self.language == "en" else "seguir con sus respuestas"
            line = self.script("session_close", sections_done=_join(done, self.language) or done_fallback,
                          next_items=_join(nxt, self.language) or next_fallback)
        line.end_call = True
        self.mode = "closed"
        self.ended = True
        self.c.session_end()
        return [line]


def secure_label(f: str, lang: str = "es") -> str:
    d = catalog.field_def(f) or {}
    label_key = "label_en" if lang == "en" else "label_es"
    if d.get("list"):
        return f"{d[label_key].split(': ')[-1].lower()} ({catalog.list_item_label(d['list'], d['index'], lang).lower()})"
    if lang == "en":
        return {"a_number": "A-number", "ssn": "Social Security number"}.get(f, d.get("label_en", f).lower())
    return {"a_number": "número A", "ssn": "número de Seguro Social"}.get(f, d.get("label_es", f).lower())


def readback_label(f: str, lang: str = "es") -> str:
    d = catalog.field_def(f) or {}
    rb_key, label_key = ("rb_en", "label_en") if lang == "en" else ("rb_es", "label_es")
    if d.get(rb_key):
        lbl = d[rb_key]
    else:
        lbl = d.get(label_key, f).split(": ")[-1].lower()
        lbl = f'"{lbl}"' if lang == "en" else f"«{lbl}»"
    m = catalog.LIST_RE.match(f)
    if m and int(m["i"]) >= 0 and m["list"] in ("trips", "addresses", "employment", "children"):
        lbl += f" ({catalog.list_item_label(m['list'], int(m['i']), lang).lower()})" if m["list"] != "trips" or int(m["i"]) > 0 else ""
    return lbl


def _join(items: list[str], lang: str = "es") -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    conj = " and " if lang == "en" else " y "
    return ", ".join(items[:-1]) + conj + items[-1]
