"""The Claude-driven assistant: ranked reminders, the focus-driven payload, permission cards, and push to talk.
The model is a stub that replays tool calls, so these run offline."""

import asyncio
import json
from types import SimpleNamespace

from ellis.db import Case, Deadline, session_scope
from ellis.services import case_service as cs, views
from ellis.voice.client import InProcessClient
from ellis.voice.llm_liaison import LlmLiaison


class _Block(dict):
    def model_dump(self, **_):
        return dict(self)


class FakeModel:
    """Stands in for anthropic.Anthropic: replays one scripted response per call and records each request."""

    def __init__(self, *responses):
        self.responses, self.calls, self.messages = list(responses), [], self

    def create(self, **kw):
        self.calls.append(kw)
        blocks = [_Block(b) for b in self.responses.pop(0)]
        return SimpleNamespace(content=blocks, stop_reason="tool_use" if any(b["type"] == "tool_use" for b in blocks)
                               else "end_turn")


def say(text):
    return [{"type": "text", "text": text}]


def use(name, **args):
    return [{"type": "tool_use", "id": f"t_{name}", "name": name, "input": args}]


def agent(case_id, *responses):
    a = LlmLiaison(InProcessClient(case_id), language="es")
    a._anthropic = FakeModel(*responses)
    return a


def test_reminders_rank_pressing_first(seeded):
    with session_scope() as s:
        case = s.get(Case, "c_maria")
        for kind, on in (("interview", "2026-12-20"), ("biometrics_appointment", "2026-10-26")):
            s.add(Deadline(clinic_id=case.clinic_id, case_id=case.id, kind=kind, date=on, proposed_by="test"))
        s.flush()
        r = views.reminders(s, case)
    assert r[0]["title"].startswith("Biometrics") and r[0]["pressing"]
    assert r[0]["when"] == "in 3 days (Monday, October 26)"
    assert not next(x for x in r if x["title"] == "USCIS interview")["pressing"]


def test_settings_change_waits_for_the_applicant(seeded):
    a = agent("c_maria",
              use("record_fact", field="consent", value=True),
              say("Gracias. ¿Empezamos por su elegibilidad?"),
              use("change_setting", setting="reply_length", value="short"),
              say("Toque Permitir en la pantalla."),
              say("Listo, respuestas cortas."))
    assert a.start()[0].kind == "disclosure"
    out = a.handle("Sí, de acuerdo")[0]
    # the opening recommends what the next-step bar shows: the first unfinished part, in form order
    with session_scope() as s:
        first = next(p for p in views.section_progress(s, s.get(Case, "c_maria")) if p["state"] != "done")
    assert out.meta["focus"]["section"] == first["section"]
    calls = a._anthropic.calls
    assert "still_needed" not in calls[0]["system"][1]["text"]
    ctx = json.loads(calls[1]["system"][1]["text"].split("\n", 1)[1])
    assert ctx["still_needed"][0]["section"] == first["section"]

    card = a.handle("Quiero respuestas más cortas")[0].meta["permissions"][0]
    assert card["title"] == "Ellis's replies: Normal → Short"
    with session_scope() as s:
        assert cs.applicant_settings(s.get(Case, "c_maria"))["reply_length"] == "normal"  # asked, not applied
    assert a.permission("nope", True) == []  # only the card the applicant was shown
    a.permission(card["id"], True)
    with session_scope() as s:
        assert cs.applicant_settings(s.get(Case, "c_maria"))["reply_length"] == "short"


def test_push_to_talk_sends_what_was_held_as_soon_as_the_turn_closes(monkeypatch):
    from ellis.api.routes import voice
    monkeypatch.setattr(voice, "PTT_MAX_WAIT_S", 5)  # waiting this long would fail the 1 s wait_for below

    async def run(before, after):
        vs = voice.VoiceSession(ws=None, case_id="c_maria")
        got, events = [], asyncio.Queue()

        async def turn(text, uncertain=False, spoken=False):
            got.append((text, spoken))
        vs.turn = turn

        class STT:
            async def events(self):
                while True:
                    yield await events.get()
        vs.stt = STT()
        loop = asyncio.create_task(vs.stt_loop())
        await events.put({"type": "turn.end", "transcript": "said before pressing"})
        await asyncio.sleep(0.01)
        await vs.on_client({"type": "talk", "down": True})
        for ev in before:
            await events.put(ev)
        await asyncio.sleep(0.01)
        await vs.on_client({"type": "talk", "down": False})
        for ev in after:
            await events.put(ev)
        await asyncio.wait_for(vs.tasks[-1], 1)
        loop.cancel()
        return got

    start, end = {"type": "turn.start"}, {"type": "turn.eager_end", "transcript": "let's start"}
    assert asyncio.run(run([start, {"type": "turn.end", "transcript": "I agree"}, start,
                            {"type": "turn.update", "transcript": "let's"}], [end])) == [("I agree let's start", True)]
    # a quick "yes": let go before Ink-2 has even opened the turn
    assert asyncio.run(run([], [start, {"type": "turn.eager_end", "transcript": "Yes."}])) == [("Yes.", True)]


def test_check_ins_stop_after_the_last_one():
    from ellis.api.routes.voice import VoiceSession
    said = []
    vs = VoiceSession(ws=None, case_id="c_maria")
    vs.last_line_end = 0
    vs.liaison = SimpleNamespace(ended=False, cfg={"silence_thresholds_s": [0, 0, 0]},
                                 silence=lambda s, last: said.append(last) or [])

    async def run():
        task = asyncio.create_task(vs.watchdog())
        await asyncio.sleep(4.2)
        task.cancel()
    asyncio.run(run())
    assert said == [False, False, True]


def test_flag_notes_skip_stop_items_conflicts_and_repeats():
    a = LlmLiaison(client=None, language="en")
    a.flags = [{"id": "f1", "category": "citation", "label_es": "Fine or citation"}, {"id": "f1", "category": "citation"},
               {"id": "f2", "speed": "stop_now"}, {"id": "f3", "category": "date_conflict", "label_es": "Date"},
               {"id": "f4", "category": "taxes"}, {"id": None, "category": "taxes"}]
    assert a._flag_notes() == [{"id": "f1", "label": "Fine or citation"}, {"id": "f4", "label": "Taxes"}]
    assert a.flags == []
