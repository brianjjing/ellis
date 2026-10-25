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


def test_tap_to_talk_waits_out_a_long_pause(monkeypatch):
    from ellis.api.routes import voice
    monkeypatch.setattr(voice, "TAP_SILENCE_S", 0.5)

    async def run():
        vs = voice.VoiceSession(ws=None, case_id="c_maria")
        got, events = [], asyncio.Queue()

        async def turn(text, uncertain=False, spoken=False):
            got.append(text)
        vs.turn = turn

        class STT:
            async def events(self):
                while True:
                    yield await events.get()
        vs.stt = STT()
        loop = asyncio.create_task(vs.stt_loop())
        await vs.on_client({"type": "talk", "down": True, "mode": "tap"})
        await events.put({"type": "turn.start"})
        await events.put({"type": "turn.end", "transcript": "I was born in"})  # Ink-2 calls the turn over
        await asyncio.sleep(0.3)
        assert got == []  # still thinking
        await events.put({"type": "turn.start"})
        await events.put({"type": "turn.eager_end", "transcript": "Oaxaca."})
        await asyncio.sleep(0.3)
        assert got == []  # the new word started the wait over
        await asyncio.wait_for(vs.tasks[-1], 1)
        loop.cancel()
        return got

    assert asyncio.run(run()) == ["I was born in Oaxaca."]


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


def test_resume_remembers_the_last_question_not_the_check_in():
    from ellis.voice.llm_liaison import last_question
    past = [("liaison", "Do you agree to continue?", "disclosure"), ("applicant", "Yes", None),
            ("liaison", "Where do you work?", "llm"), ("liaison", "Are you still there?", "checkin")]
    assert last_question(past) == ("Where do you work?", False)
    assert last_question(past + [("applicant", "At a packing plant", None)]) == ("Where do you work?", True)
    assert last_question(past[:1]) is None


def test_dates_are_not_sensitive_numbers():
    from ellis.services.keywords import has_sensitive_number, redact_numbers
    for said in ("I was born 09/11/1995", "since 1995-09-11", "from 2015-2019", "el 05 02 1988", "9 11 1995"):
        assert not has_sensitive_number(said), said
    for said in ("my A number is 123456789", "123-45-6789", "A 12345678", "uno dos tres cuatro cinco seis siete"):
        assert has_sensitive_number(said), said
    assert redact_numbers("born 1995-09-11, A 123456789") == "born 1995-09-11, A [REDACTED_NUMBER]"


def test_a_reply_overtaken_by_a_newer_turn_is_never_spoken():
    import threading
    from ellis.api.routes.voice import VoiceSession
    from ellis.voice.liaison import Say
    thinking, calls = threading.Event(), []

    def handle(text, field, word, uncertain, unheard):
        calls.append((text, unheard))
        if text == "first":
            thinking.wait(2)  # still preparing this reply when the second turn comes in
        return [Say(f"reply to {text}")]
    vs = VoiceSession(ws=None, case_id="c_maria")
    vs.liaison = SimpleNamespace(ended=False, handle=handle)

    async def run():
        first = asyncio.create_task(vs.turn("first"))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(vs.turn("second"))
        await asyncio.sleep(0.05)
        thinking.set()
        await asyncio.gather(first, second)
    asyncio.run(run())
    assert calls == [("first", False), ("second", True)]
    assert vs.q.get_nowait().text == "reply to second" and vs.q.empty()


def test_the_model_sees_what_was_withheld_or_unheard(seeded):
    from ellis.voice.llm_liaison import STOP_NOTE
    a = agent("c_maria", use("record_fact", field="consent", value=True), say("¿Empezamos?"), say("Bien."))
    a.start()
    a.handle("Sí, de acuerdo")
    a.handle("Mi número es 123456789 y me mudé el 2021-03-01")  # the number is taken out, the date still counts
    assert "123456789" not in str(a.history) and "me mudé el 2021-03-01" in str(a.history)
    a.handle("No", interrupted_at_word="viajado")
    assert a.history[-2]["content"] == 'No\n[they cut you off at "viajado": they never heard the rest of your last reply]'
    a.handle("No, porque me arrestaron en 2016")  # stored as [STOP:arrest]
    b = agent("c_maria", say("Hola de nuevo."))
    b.start()  # a resume: memory comes from the stored transcript
    texts = [m["content"] for m in b.history if isinstance(m["content"], str)]
    assert not any("STOP:" in t for t in texts) and any(STOP_NOTE in t for t in texts)


def test_live_case_data_is_built_between_turns_and_checked_with_one_query(seeded):
    a = agent("c_jorge",
              use("request_upload", document_type="passport"), use("set_focus", task="general", next_step="Hi"),
              say("Suba su pasaporte."),
              use("record_fact", field="employment[0].employer", value="Acme Foods"), say("Gracias."),
              say("Su clínica agregó una nota."))
    builds, checks = [], []
    real_build, real_check = a.c.case_context, a.c.latest_event_id
    a.c.case_context = lambda focus: builds.append(dict(focus)) or real_build(focus)
    a.c.latest_event_id = lambda: checks.append(1) or real_check()
    a.cfg = {"consent_given": True}

    a.handle("Tengo mi pasaporte")
    # three model rounds, two builds: a card tool keeps the data, the new focus needs it again;
    # then the next turn's data is built after the reply
    assert len(a._anthropic.calls) == 3
    a._prefetch.result()
    assert len(builds) == 3 and builds[-1]["task"] == "general" and checks == []

    a.handle("Trabajo en Acme Foods")
    # the turn starts with one check (nothing changed: the prefetched data is used); record_fact wrote, so the
    # round after it builds again; then the next turn's data is prefetched
    a._prefetch.result()
    assert len(checks) == 1 and len(builds) == 5

    with session_scope() as s:  # someone else changes the case between turns
        cs.emit(s, s.get(Case, "c_jorge"), "note.added", {"memo_id": "m_x"}, "staff", "u_x")
    a.handle("¿Hay algo nuevo?")
    a._prefetch.result()
    assert len(checks) == 2 and len(builds) == 7  # the check saw the new event: built again (+ the prefetch)


def test_saving_ellis_lines_never_holds_up_the_reply(seeded):
    import time
    a = agent("c_jorge", say("¿Dónde trabaja?"))
    a.cfg = {"consent_given": True}
    real = a.c.liaison_said
    a.c.liaison_said = lambda *args: time.sleep(0.5) or real(*args)
    t0 = time.time()
    assert a.handle("Hola")[0].text == "¿Dónde trabaja?"
    assert time.time() - t0 < 0.4
    from ellis.voice.llm_liaison import _CAPTIONS
    _CAPTIONS.submit(lambda: None).result()  # a resume waits for this too
    said = [t for who, t, _ in a.c.recent_transcript() if who == "liaison"]
    assert said[-1] == "¿Dónde trabaja?"


def _voice_ws(client, monkeypatch, *responses, delay=0.0):
    """Sign in as Jorge (consent given) and open WS /api/a/voice with a scripted model and no Cartesia key."""
    import time
    from ellis.config import settings
    from ellis.voice import llm_liaison
    monkeypatch.setattr(type(settings), "anthropic_api_key", property(lambda self: "test"))
    monkeypatch.setattr(type(settings), "cartesia_api_key", property(lambda self: None))
    model = FakeModel(*responses)
    real = model.create

    def slow(**kw):
        time.sleep(delay)
        return real(**kw)
    model.create = slow
    monkeypatch.setattr(llm_liaison.LlmLiaison, "_client_", lambda self: model)
    assert client.post("/api/a/session", json={"token": "demo-jorge"}).status_code == 200
    return model


def _until(ws, kind, seen):
    while True:
        m = ws.receive_json()
        seen.append(m)
        if m["type"] == kind:
            return m


def test_the_mic_is_ready_before_ellis_opening_line(client, monkeypatch):
    model = _voice_ws(client, monkeypatch, say("Bienvenido otra vez, Jorge."), say("Anotado: Acme Foods."),
                      say("Hasta luego."))
    with client.websocket_connect("/api/a/voice") as ws:
        ws.send_json({"type": "start", "voice": False, "language": "es", "locale": "es-MX"})
        seen = []
        ready = _until(ws, "ready", seen)
        assert ready["mode"] == "text" and ready["talk_unavailable"]
        assert not any(m["type"] == "line" for m in seen)  # ready came first
        line = _until(ws, "line", seen)
        assert line["text"] == "Bienvenido otra vez, Jorge."
        ws.send_json({"type": "text", "text": "Trabajo en Acme Foods"})
        assert _until(ws, "user_final", seen)["text"] == "Trabajo en Acme Foods"
        assert _until(ws, "line", seen)["text"] == "Anotado: Acme Foods."
        ws.send_json({"type": "end"})
    assert len(model.calls) >= 2  # the opening and the turn (the goodbye may still be running)


def test_typing_before_the_opening_is_ready_loses_neither_line(client, monkeypatch):
    model = _voice_ws(client, monkeypatch, say("Hola de nuevo."), say("Claro, le explico."), say("Hasta luego."),
                      delay=0.4)
    with client.websocket_connect("/api/a/voice") as ws:
        ws.send_json({"type": "start", "voice": False, "language": "es", "locale": "es-MX"})
        seen = []
        _until(ws, "ready", seen)
        ws.send_json({"type": "text", "text": "¿Qué documentos necesito?"})  # while the opening is prepared
        lines = [_until(ws, "line", seen)["text"], _until(ws, "line", seen)["text"]]
        ws.send_json({"type": "end"})
    assert lines == ["Hola de nuevo.", "Claro, le explico."]
    # the model is told the question came before the opening reached them
    turn = next(m["content"] for m in model.calls[1]["messages"]
                if isinstance(m["content"], str) and "¿Qué documentos necesito?" in m["content"])
    assert "never heard it" in turn
