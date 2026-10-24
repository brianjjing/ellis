"""Case API client for the liaison: in-process (same FastAPI process) or HTTP (/tools/*, for a Line deployment).

Both expose the same methods, one per liaison tool, and both bake in the case id (constant_value in Line).
"""

from __future__ import annotations

from typing import Any

import httpx


class InProcessClient:
    def __init__(self, case_id: str, session_id: str | None = None):
        self.case_id = case_id
        self.session_id = session_id

    def _run(self, fn):
        from ..db import Case, session_scope
        with session_scope() as s:
            case = s.get(Case, self.case_id)
            return fn(s, case)

    def session_start(self, channel: str = "voice") -> dict[str, Any]:
        from ..api.routes.tools import call_config, start_session

        def f(s, case):
            sess = start_session(s, case, channel)
            self.session_id = sess.id
            return {"session_id": sess.id, **call_config(s, case)}
        return self._run(f)

    def session_end(self) -> None:
        from ..db import CallSession, now
        from ..services import case_service as cs

        def f(s, case):
            sess = s.get(CallSession, self.session_id) if self.session_id else None
            if sess and sess.ended_at is None:
                sess.ended_at = now()
                cs.emit(s, case, "session.ended", {"session_id": sess.id}, "liaison", "liaison")
        self._run(f)

    def get_briefing(self) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.liaison_briefing(s, case))

    def agent_context(self, focus: dict[str, Any]) -> dict[str, Any]:
        from ..services import views
        return self._run(lambda s, case: views.agent_context(s, case, focus))

    def call_config(self) -> dict[str, Any]:
        from ..api.routes.tools import call_config
        return self._run(call_config)

    def set_setting(self, setting: str, value: str) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.set_setting(s, case, setting, value))

    def ask_clinic(self, question: str) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.ask_clinic(s, case, question))

    def recent_transcript(self, limit: int = 24) -> list[tuple[str, str]]:
        """Last turns (speaker, text) for this case, oldest first -- context for a resumed conversation."""
        from sqlalchemy import select

        from ..db import Utterance

        def f(s, case):
            rows = s.scalars(select(Utterance).where(Utterance.case_id == case.id)
                             .order_by(Utterance.ts.desc()).limit(limit)).all()
            return [(u.speaker, u.text) for u in reversed(rows)]
        return self._run(f)

    def record_fact(self, field: str, value: Any, hedge: bool = False, utterance_id: str | None = None,
                    interrupted_at_word: str | None = None, is_correction: bool = False,
                    utterance_text: str | None = None) -> dict[str, Any]:
        from ..services import case_service as cs

        def f(s, case):
            try:
                return cs.record_fact(s, case, field, value, hedge=hedge, utterance_id=utterance_id,
                                      session_id=self.session_id, interrupted_at_word=interrupted_at_word,
                                      is_correction=is_correction, utterance_text=utterance_text)
            except cs.CaseError as e:
                return {"saved": False, "error": {"code": e.code, "message": e.message, "field": e.field}}
        return self._run(f)

    def read_back(self, field: str, read_value: str | None = None, briefing_version: int | None = None,
                 lang: str = "es") -> dict:
        from ..services import case_service as cs

        def f(s, case):
            try:
                return cs.read_back(s, case, field, briefing_version, read_value, lang=lang)
            except cs.CaseError as e:
                return {"error": {"code": e.code, "message": e.message}}
        return self._run(f)

    def flag_for_review(self, category: str, field: str | None = None) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.flag_for_review(s, case, category, field))

    def stop_script(self, category: str) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.stop_now(s, case, category, layer=3, session_id=self.session_id))

    def request_secure_entry(self, field: str) -> None:
        from ..services import case_service as cs, catalog

        def f(s, case):
            label = catalog.label_en(field) if cs.case_lang(case) == "en" else catalog.label_es(field)
            cs.push(s, case, "open_secure_entry", {"field": field, "label": label,
                                                   "type": (catalog.field_def(field) or {}).get("type")})
        self._run(f)

    def request_upload(self, document_type: str) -> None:
        from ..services import case_service as cs
        from ..services.documents import document_label
        self._run(lambda s, case: cs.push(s, case, "open_upload", {"document_type": document_type,
                                                                   "label": document_label(document_type, cs.case_lang(case))}))

    def request_biographics(self) -> None:
        from ..services import case_service as cs
        self._run(lambda s, case: cs.push(s, case, "open_biographics", {}))

    def applicant_turn(self, text: str) -> dict[str, Any]:
        from ..services import case_service as cs
        return self._run(lambda s, case: cs.applicant_turn(s, case, text, self.session_id))

    def liaison_said(self, text: str, locked: bool = False, meta: dict | None = None) -> None:
        from ..services import case_service as cs

        def f(s, case):
            cs.liaison_utterance(s, case, text, self.session_id, locked, meta)
            cs.push(s, case, "caption", {"speaker": "liaison", "text": text, "locked": locked})
        self._run(f)

    def third_party(self, present: bool, relation: str | None) -> None:
        from ..db import CallSession
        from ..services import case_service as cs

        def f(s, case):
            sess = s.get(CallSession, self.session_id) if self.session_id else None
            if sess:
                sess.third_party_present = present
                sess.third_party_relation = relation
            cs.emit(s, case, "session.third_party", {"present": present, "relation": relation}, "liaison", "liaison")
        self._run(f)

    def stop_spoken(self) -> None:
        from ..services import case_service as cs
        self._run(lambda s, case: cs.emit(s, case, "stop.spoken", {"script_version": "es-1"}, "liaison", "liaison"))


class HttpClient:
    """Calls the Case API's /tools/* endpoints (used by the Line agent deployed to Cartesia)."""

    def __init__(self, base_url: str, tool_secret: str, case_id: str, timeout: float = 5.0):
        self.case_id = case_id
        self.session_id: str | None = None
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout,
                                 headers={"Authorization": f"Bearer {tool_secret}", "X-Ellis-Case": case_id})

    def _post(self, path: str, body: dict | None = None) -> Any:
        headers = {"X-Ellis-Session": self.session_id} if self.session_id else {}
        r = self.http.post(f"/tools/{path}", json=body or {}, headers=headers)
        r.raise_for_status()
        return r.json()

    def session_start(self, channel: str = "line") -> dict[str, Any]:
        out = self._post("session_start", {"channel": channel})
        self.session_id = out["session_id"]
        return out

    def session_end(self) -> None:
        self._post("session_end")

    def get_briefing(self) -> dict[str, Any]:
        return self._post("get_briefing")

    def record_fact(self, field, value, hedge=False, utterance_id=None, interrupted_at_word=None,
                    is_correction=False, utterance_text=None) -> dict[str, Any]:
        return self._post("record_fact", {"field": field, "value": value, "hedge": hedge,
                                          "utterance_id": utterance_id, "interrupted_at_word": interrupted_at_word,
                                          "is_correction": is_correction, "utterance_text": utterance_text})

    def read_back(self, field, read_value=None, briefing_version=None) -> dict[str, Any]:
        try:
            return self._post("read_back", {"field": field, "read_value": read_value,
                                            "briefing_version": briefing_version})
        except httpx.HTTPStatusError as e:
            return {"error": {"code": "http", "message": str(e)}}

    def flag_for_review(self, category, field=None) -> dict[str, Any]:
        return self._post("flag_for_review", {"category": category, "field": field})

    def stop_script(self, category) -> dict[str, Any]:
        return self._post("stop_script", {"category": category})

    def request_secure_entry(self, field) -> None:
        self._post("request_secure_entry", {"field": field})

    def request_upload(self, document_type) -> None:
        self._post("request_upload", {"document_type": document_type})

    def request_biographics(self) -> None:
        self._post("request_biographics")

    def applicant_turn(self, text) -> dict[str, Any]:
        return self._post("applicant_turn", {"text": text})

    def liaison_said(self, text, locked=False, meta=None) -> None:
        self._post("liaison_said", {"text": text, "locked": locked})

    def third_party(self, present, relation) -> None:
        self._post("third_party", {"present": present, "relation": relation})

    def stop_spoken(self) -> None:
        pass
