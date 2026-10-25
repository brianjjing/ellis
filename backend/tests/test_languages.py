"""Every language and accent Cartesia's Sonic speaks: the registry, the pickers' API, and what follows from a case's
locale (the conversation language, Ellis's own text language, the speech-to-text model)."""

from ellis.db import Case, session_scope
from ellis.services import case_service as cs, languages


def test_registry_covers_cartesias_languages_and_accents():
    cat = {x["code"]: x for x in languages.catalog()}
    assert len(cat) == 44
    assert [loc["code"] for loc in cat["fr"]["locales"]] == ["fr-FR", "fr-CA"]
    assert languages.normalize("fr_ca") == "fr-CA" and languages.normalize("pt") == "pt-BR"
    assert languages.normalize("es-AR") is None and languages.normalize("xx-YY") is None
    assert languages.name("fr-CA") == "French (Canada)" and languages.name("vi-VN") == "Vietnamese"
    assert languages.native_name("es-MX") == "Español (México)"
    # Ink-2 hears five languages with turn detection; ink-whisper the rest; nothing hears Odia
    assert languages.stt_model("ja-JP") == "ink-2" and languages.stt_model("vi-VN") == "ink-whisper"
    assert languages.stt_model("or-IN") is None
    assert languages.is_rtl("ar") and languages.is_rtl("he-IL") and not languages.is_rtl("fr-FR")


def test_a_french_case_talks_french_but_reads_english_not_spanish(seeded):
    with session_scope() as s:
        case = s.get(Case, "c_maria")
        case.language = "fr-CA"
        assert cs.case_language(case) == "fr"
        assert cs.case_lang(case) == "en"  # Ellis's own text: English, never Spanish, for a non-Spanish language
        from ellis.services import views
        assert views.agent_context(s, case, {"task": "general"})["reply_language"] == "French (Canada)"


def test_language_endpoints_accept_every_supported_accent(client):
    langs = client.get("/api/languages").json()["languages"]
    assert {x["code"] for x in langs} >= {"en", "es", "vi", "tl", "zh", "ar"}
    assert client.post("/api/a/session", json={"token": "demo-maria"}).status_code == 200
    assert client.post("/api/a/language", json={"locale": "pt_br"}).json()["language"] == "pt-BR"
    assert client.post("/api/a/language", json={"locale": "xx-YY"}).status_code == 400
    with session_scope() as s:
        assert s.get(Case, "c_maria").language == "pt-BR"
        assert "vi-VN" in cs.APPLICANT_SETTINGS["language"]  # Ellis can offer it through change_setting


class _WS:
    """Stands in for a Cartesia websocket: records what is sent, replays scripted messages."""

    def __init__(self, incoming=()):
        self.sent, self.incoming = [], list(incoming)

    async def send(self, m):
        self.sent.append(m)

    async def recv(self):
        return self.incoming.pop(0)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.incoming:
            raise StopAsyncIteration
        return self.incoming.pop(0)


def test_sonic_gets_the_accent_as_locale_and_older_models_the_language(monkeypatch):
    import asyncio
    import json
    from ellis.voice import cartesia
    for model, key, want in (("sonic-3.6", "locale", "fr-CA"), ("sonic-3", "language", "fr")):
        monkeypatch.setenv("CARTESIA_TTS_MODEL", model)
        tts = cartesia.TTS(locale="fr-CA", voice_id="v_1")
        tts.ws = _WS([json.dumps({"type": "done", "done": True})])

        async def run():
            return [p async for p in tts.speak("Bonjour")]
        asyncio.run(run())
        req = json.loads(tts.ws.sent[0])
        assert req[key] == want and ({"locale", "language"} - {key}).isdisjoint(req)


def test_ink_whisper_speaks_the_same_turn_events():
    import asyncio
    import json
    from ellis.voice import cartesia
    stt = cartesia.STT(model="ink-whisper", language="vi")
    assert stt.manual
    stt.ws = _WS([json.dumps(m) for m in (
        {"type": "transcript", "is_final": False, "text": "Tôi làm"},
        {"type": "transcript", "is_final": True, "text": "Tôi làm ở Acme."},
        {"type": "transcript", "is_final": True, "text": "  "},
        {"type": "flush_done"}, {"type": "done"})])

    async def run():
        await stt.finalize()
        return [e async for e in stt.events()]
    assert asyncio.run(run()) == [{"type": "turn.update", "transcript": "Tôi làm"},
                                  {"type": "turn.end", "transcript": "Tôi làm ở Acme."}, {"type": "turn.flushed"}]
    assert stt.ws.sent == ["finalize"]


def test_voices_recorded_in_the_accent_come_first(monkeypatch):
    import asyncio
    from ellis.voice import cartesia

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [
                {"id": "speaks_fr", "accents": [{"accent": "parisian", "locale": "fr-FR", "is_native": False}]},
                {"id": "speaks_ca", "accents": [{"accent": "canadian-french", "locale": "fr-CA", "is_native": False}]},
                {"id": "native_ca", "accents": [{"accent": "canadian-french", "locale": "fr-CA", "is_native": True}]}]}

    class C:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, url, headers=None, params=None):
            assert params["language"] == "fr-CA"
            return R()
    monkeypatch.setattr(cartesia.httpx, "AsyncClient", C)
    cartesia._list_cache.clear()
    assert [v["id"] for v in asyncio.run(cartesia.voices("fr-CA"))] == ["native_ca", "speaks_ca", "speaks_fr"]


def test_ink_whisper_turn_waits_for_the_flush_and_tap_needs_a_second_tap(monkeypatch):
    import asyncio
    from ellis.api.routes import voice

    async def run():
        vs = voice.VoiceSession(ws=None, case_id="c_maria")
        got, events = [], asyncio.Queue()

        async def turn(text, uncertain=False, spoken=False):
            got.append(text)
        vs.turn = turn

        class STT:
            manual = True

            async def finalize(self):
                await events.put({"type": "turn.end", "transcript": "the rest"})
                await events.put({"type": "turn.flushed"})

            async def events(self):
                while True:
                    yield await events.get()
        vs.stt = STT()
        loop = asyncio.create_task(vs.stt_loop())
        await vs.on_client({"type": "talk", "down": True, "mode": "tap"})
        await events.put({"type": "turn.end", "transcript": "first part"})
        await asyncio.sleep(0.05)
        assert got == []  # a final piece is not the end of a tap turn here
        await vs.on_client({"type": "talk", "down": False})
        await asyncio.wait_for(vs.tasks[-1], 2)
        loop.cancel()
        return got
    assert asyncio.run(run()) == ["first part the rest"]


def test_a_new_language_clears_the_chosen_voice_and_unknown_voices_are_refused(client, monkeypatch):
    from ellis.config import settings
    from ellis.voice import cartesia
    assert client.post("/api/a/session", json={"token": "demo-maria"}).status_code == 200
    monkeypatch.setattr(type(settings), "cartesia_api_key", property(lambda self: "k"))

    async def fake(locale):
        return [{"id": "v_mx", "name": "Lucía", "accents": [{"locale": "es-MX", "accent": "mexican"}]}]
    monkeypatch.setattr(cartesia, "voices", fake)
    assert client.get("/api/a/voices").json()["voices"][0] == {
        "id": "v_mx", "name": "Lucía", "description": None, "gender": None, "preview_url": None, "accent": "mexican"}
    assert client.post("/api/a/voice", json={"voice_id": "nope"}).status_code == 400
    assert client.post("/api/a/voice", json={"voice_id": "v_mx"}).status_code == 200
    with session_scope() as s:
        assert s.get(Case, "c_maria").settings["voice_id"] == "v_mx"
    client.post("/api/a/language", json={"locale": "fr-CA"})
    with session_scope() as s:
        assert "voice_id" not in s.get(Case, "c_maria").settings
