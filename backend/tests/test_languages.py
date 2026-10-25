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
