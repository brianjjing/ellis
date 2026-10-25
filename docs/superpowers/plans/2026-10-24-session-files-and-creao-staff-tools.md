# Session Files, Cartesia Paths, and Creao Staff Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After every applicant session, the clinic and the applicant can see and download every file that session produced. Both Cartesia paths (web gateway and hosted Line agent) persist the complete transcript and close their sessions. Saved Creao agents replace the skeleton staff agents by calling our role-scoped MCP server, which also proxies our own external tools and external MCPs (email first) behind an approval gate.

**Architecture:** Part A gives each file (upload, packet, new session summary) a DB row, a session link and a stable on-disk path, and serves them all through one files endpoint per audience. Part B makes the Line agent report every turn and the end of every call to `/tools/*`, the same way the web gateway already does in-process. Part C adds a framework-agnostic staff-tool registry (`ellis/staff_tools/`). Creao reaches it through one MCP endpoint per role (`/mcp/<agent>/`). Agent writes are staged on the job and applied once through the existing `validate_envelope` → `apply_proposal` path. External MCP servers (email) are reached only through our server, so the role scoping, work log, redaction and "nothing leaves without reviewer approval" rules all live in code.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, pydantic 2, reportlab, pytest, `mcp` Python SDK (new), cartesia-line (optional extra), React + TypeScript (Vite).

**Spec:** This plan implements (1) the diagnosis findings F1–F8 below, (2) `docs/oneshot.md` §"Case API and MCP server" and §"Staff agents (Creao)" (lines ~1032–1127), and (3) these user requirements: Creao agents plug into the agent runner in place of the skeletons; agents can call tools we write and external MCPs such as email to get outside information; a later agent must be able to read this plan plus `docs/creao-integration.md` and finish the Creao hookup.

### Diagnosis findings (the bugs this plan fixes)

- **F1** A voice session produces no files and no per-session record. `document` has no `session_id`, and nothing links a packet or upload to the session it came from.
- **F2** `seed.load(reset=True)` runs `drop_all()` but never clears `data/files/`, so each `scripts/dev.sh` run orphans every earlier upload (observed: 255 files on disk, 4 `document` rows).
- **F3** Packet PDFs survive on disk without `packet` rows, so neither UI can see them (both UIs list only what has a row).
- **F4** `packet/builder.py:173` writes `packet/{kind}.pdf`. A rebuild overwrites the previous file while superseded `packet` rows still point at that path, so their `sha256` no longer matches.
- **F5** With `ELLIS_LINE_BRAIN=llm`, `KeywordGuard` sends applicant turns to `/tools/applicant_turn` only on stop-list or sensitive-number hits, and never sends Claude's lines to `/tools/liaison_said`. The clinic transcript ends up nearly empty.
- **F6** With the LLM brain, `CallEnded` never calls `session_end`, so sessions stay open. Separately, `VoiceSession.shutdown` skips `session_end` whenever `liaison.ended` is already true.
- **F7** `line_app.py` uses `ELLIS_API_URL` (default `http://localhost:8000`), while `CreaoBackend` uses `ELLIS_PUBLIC_API_URL`. A Cartesia-hosted agent can't reach localhost. `line_app` also reads `ELLIS_TOOL_SECRET` from `os.environ` instead of `settings`, `HttpClient.read_back` drops `lang`, and `/tools/liaison_said` never pushes a caption.
- **F8** When the web gateway falls back from Cartesia to text, nothing records why, and `session.channel` reflects what was requested rather than what actually ran.

## Global Constraints

- Backend commands run from `backend/`: tests are `uv run pytest`, and Line tests are `uv run --extra line pytest tests/test_line_app.py`.
- New dependency: only `mcp>=1.12`, added to `[project].dependencies` in `backend/pyproject.toml`. No others.
- Agents never write directly. Every agent write reaches the DB through `validate_envelope` + `apply_proposal` (`ellis/agents/proposals.py`). No tool, for any role, approves a review item, signs, builds a packet, or files anything.
- Nothing leaves the building without approval. Any tool of kind `external_action` only creates a pending `OutboundAction`. Only a staff user with role `reviewer` or `admin` can make it execute.
- Event payloads never carry tool arguments, tool results, or sensitive values. Stop-list text is never persisted raw (`[STOP:<category>]` only). Request bodies under `/tools/*` and `/mcp/*` are never logged.
- The applicant never sees `reviewer_summary`, flags, stop-now categories, or another case's files.
- Fail closed when a secret is unset: the Creao webhook (existing), every MCP role token (`ELLIS_MCP_TOKEN_<AGENT>`), and every external connector token.
- Wherever a Creao API field name is guessed, leave `TODO(open-question-7)`, matching the existing convention in `backends.py`.
- There is no migration framework: dev reseeds with `drop_all`/`create_all`. For each new column on an existing table, also add `ALTER TABLE <t> ADD COLUMN IF NOT EXISTS ...` inside the `if is_postgres():` block of `create_all()` in `ellis/db.py`. New tables need nothing extra.
- Applicant-facing copy exists in both `en` and `es`, using the existing `lang === 'en' ? … : …` pattern.
- Another session is editing `backend/ellis/voice/liaison.py`, `english.py`, `scripts_*.yaml`, `case_service.py`, `seed/load.py`, `frontend/src/applicant/Review.tsx` and `scripts/dev.sh`. Before starting, confirm with the user that its work is committed, and rebase onto it. Never edit `Review.tsx` in this plan.
- Run ids get longer: `Runner.claim` uses `f"run_{secrets.token_hex(12)}"` (Task 9). Nothing else may assume 8 hex characters.

## Review Focus

1. **An agent sends a `run_id` that belongs to another role, another case, a finished run or an expired run.** It must get an error and stage nothing. Test: Task 9, `test_call_rejects_run_of_other_role` and `test_call_rejects_finished_or_expired_run`.
2. **Creao delivers the webhook twice, before `finish_run`, after it, or never.** Items must be applied exactly once, and a run that never finishes must be failed with nothing written. Test: Task 12, `test_webhook_after_finish_run_is_noop`, `test_webhook_without_finish_run_applies_staged`, `test_runner_expires_stale_dispatch`.
3. **Someone opens an older signed link to a superseded packet after a rebuild.** They must get the original bytes, matching that row's sha256. Test: Task 5, `test_superseded_packet_url_serves_original_bytes`.
4. **An applicant's file list or summary PDF must never leak** `reviewer_summary`, stop-now text, full vault numbers, or another case's file. A URL signed for one kind must not open a different kind. Test: Task 4 `test_summary_omits_stop_now_and_vault_digits`, Task 5 `test_applicant_files_hide_reviewer_summary_and_other_cases`, `test_signed_url_kind_cannot_be_swapped`.
5. **The external email MCP is down when a reviewer approves a send.** The action must be marked `failed` with the error visible and must stay retryable, never shown as `sent`. Test: Task 13, `test_failed_send_is_retryable`.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `backend/seed/load.py` | modify | clear `settings.files_dir` on reset |
| `backend/ellis/packet/builder.py` | modify | write each packet to `packet/<packet_id>/<filename>` |
| `backend/ellis/db.py` | modify | `Document.session_id`, `SessionArtifact`, `Job.staged`, `OutboundAction` |
| `backend/ellis/services/case_service.py` | modify | `end_session()`, the single place a session ends |
| `backend/ellis/services/session_files.py` | create | build the per-session summary PDF |
| `backend/ellis/services/views.py` | modify | `case_files()` for both audiences |
| `backend/ellis/api/routes/applicant.py` | modify | kind-aware signed URLs, `/files/{kind}/{id}`, `GET /api/a/files`, session id on upload |
| `backend/ellis/api/routes/clinic.py` | modify | `GET /cases/{id}/files`, outbound action list and decision |
| `backend/ellis/api/routes/tools.py` | modify | use `end_session`; `liaison_said` pushes caption and meta; `read_back` takes `lang` |
| `backend/ellis/api/routes/voice.py` | modify | record the fallback reason and actual channel; always end on shutdown |
| `backend/ellis/voice/client.py` | modify | `InProcessClient.session_end` uses `end_session`; `HttpClient` sends `lang` and `meta` |
| `backend/ellis/voice/line_app.py` | modify | full transcript, session end, `settings.public_api_url`, `settings.tool_secret` |
| `backend/ellis/config.py` | modify | `public_api_url` setting |
| `backend/ellis/staff_tools/__init__.py` | create | import `case_tools`, then register connector tools |
| `backend/ellis/staff_tools/registry.py` | create | `StaffTool`, `RunCtx`, `ToolError`, `register`, `tools_for`, `call` |
| `backend/ellis/staff_tools/runs.py` | create | `resolve_run`, `stage`, `finalize`, `expire_dispatched` |
| `backend/ellis/staff_tools/case_tools.py` | create | `get_case`, `rules_engine`, generated `propose_*`, `finish_run` |
| `backend/ellis/staff_tools/mcp_server.py` | create | low-level MCP server per role, bearer auth ASGI wrapper, mount |
| `backend/ellis/staff_tools/connectors.py` | create | external MCP bridge, `external_read` redaction, `external_action` approval |
| `backend/config/connectors.yaml` | create | connector config (email example, disabled until env set) |
| `backend/ellis/agents/proposals.py` | modify | extract `authority_reason()` (shared by staging and apply) |
| `backend/ellis/agents/runner.py` | modify | dispatched lifecycle, longer run ids, expiry sweep |
| `backend/ellis/agents/backends.py` | modify | Creao dispatch input, `settings.public_api_url` |
| `backend/ellis/api/routes/webhooks.py` | modify | run completion via `finalize`, BackgroundTasks |
| `backend/ellis/api/app.py` | modify | mount MCP apps, run their session managers in lifespan |
| `backend/ellis/agents/charters.py` | create | `charter_for(agent)`, the text to paste into Creao |
| `backend/prompts/creao_contract.md` | create | shared tool-use rules for Creao agents |
| `backend/.env.example` | modify | new env vars |
| `docs/creao-integration.md` | create | handoff runbook for the Creao transition |
| `frontend/src/clinic/CaseDetail.tsx` | modify | Files tab, Approvals tab |
| `frontend/src/applicant/Files.tsx` | create | `YourFiles` list |
| `frontend/src/applicant/ApplicantApp.tsx` | modify | render `YourFiles` in `Progress` |
| `backend/tests/test_storage.py` | create | Part A tests |
| `backend/tests/test_line_app.py` | create | Part B Line tests |
| `backend/tests/test_voice_paths.py` | create | Part B gateway and `/tools` tests |
| `backend/tests/test_staff_tools.py` | create | registry, runs, case tools |
| `backend/tests/test_mcp_server.py` | create | MCP HTTP contract |
| `backend/tests/test_creao.py` | create | dispatch, webhook, expiry, simulated end-to-end Creao run |
| `backend/tests/test_connectors.py` | create | external tools and approvals |

Execution order is task order. Parts A, B and C don't depend on each other's behavior, but they all edit `db.py`, `app.py` and `case_service.py`, so run them sequentially (or in separate worktrees, merged in order A → B → C).

---

## Part A — Every session's files are visible

### Task 1: Seed reset leaves no orphan files (F2)

**Files:**
- Modify: `backend/seed/load.py` (`load()`, around line 39)
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces: `load(reset=True)` guarantees that `settings.files_dir` holds only files referenced by DB rows.

- [ ] **Step 1: Write the failing test**

```python
def test_reseed_leaves_no_orphan_files(seeded):
    from seed import load
    load.load(reset=True)
    with session_scope() as s:
        paths = {d.storage_path for d in s.scalars(select(Document))}
    on_disk = {str(p) for p in settings.files_dir.rglob("*") if p.is_file()}
    assert on_disk == paths
    assert all(Path(p).exists() for p in paths)
```

- [ ] **Step 2: Run it and confirm it fails** — `uv run pytest tests/test_storage.py::test_reseed_leaves_no_orphan_files -v`. Expected: FAIL, because the first seed's files remain.
- [ ] **Step 3: Implement.** In `load()`, when `reset` is true, call `shutil.rmtree(settings.files_dir, ignore_errors=True)` before `drop_all()`. `settings.files_dir` recreates the directory on next access.
- [ ] **Step 4: Run it and confirm it passes** — same command. Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "fix(seed): clear file storage on reset so reseeding leaves no orphans"`

### Task 2: Packet files are versioned per packet (F3, F4)

**Files:**
- Modify: `backend/ellis/packet/builder.py:148-298`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces: each `Packet` row's `storage_path` is `files_dir/<case_id>/packet/<packet_id>/<filename>`, unique per row and never overwritten.

- [ ] **Step 1: Write the failing test**

```python
def test_rebuilt_packets_keep_their_own_bytes(seeded):
    from ellis.services import signoff
    with session_scope() as s:
        case = s.get(Case, "c_jorge")
        a = signoff.professional_draft(s, case)
        b = signoff.professional_draft(s, case)
        assert a.storage_path != b.storage_path
        for p in (a, b):
            assert hashlib.sha256(Path(p.storage_path).read_bytes()).hexdigest() == p.sha256
```

- [ ] **Step 2: Run it and confirm it fails** (both rows share `packet/professional_draft.pdf`).
- [ ] **Step 3: Implement.** In `build_packet`, for each kind, set `pk_id = new_id("p")` first, set `path = folder / pk_id / fn`, run `path.parent.mkdir(parents=True, exist_ok=True)`, and construct `Packet(id=pk_id, ...)`.
- [ ] **Step 4: Run `uv run pytest tests/test_storage.py tests/test_acceptance.py -k "packet or at15"` and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "fix(packet): write each packet version to its own path"`

### Task 3: One way to end a session, and session-linked uploads (F1, F6)

**Files:**
- Modify: `backend/ellis/db.py` (add `Document.session_id`, plus a Postgres `ALTER`)
- Modify: `backend/ellis/services/case_service.py` (add `end_session`)
- Modify: `backend/ellis/api/routes/tools.py` (`start_session`, `session_end` route)
- Modify: `backend/ellis/voice/client.py` (`InProcessClient.session_end`)
- Modify: `backend/ellis/api/routes/voice.py` (`VoiceSession.shutdown`)
- Modify: `backend/ellis/services/documents.py` (`store_upload` takes `session_id`)
- Modify: `backend/ellis/api/routes/applicant.py` (`upload` passes the active session id)
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces: `end_session(s: Session, case: Case, sess: CallSession, reason: str) -> None`. It is idempotent: if `sess.ended_at` is already set it does nothing. Otherwise it sets `ended_at` and emits `session.ended` with payload `{"session_id", "reason"}`, actor `liaison`. `reason` ∈ `{"liaison", "client", "superseded", "disconnect"}`.
- Produces: `Document.session_id: str | None` (String(40), nullable, indexed).
- Produces: `store_upload(s, case, document_type, filename, data, *, session_id: str | None = None, ...)`, which keeps the existing parameters.
- Consumes: `active_session(s, case, request=None, create=False)` from `routes/tools.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_end_session_idempotent_single_event(client):
    sid = tool(client, "c_maria", "session_start", {"channel": "line"})["session_id"]
    tool(client, "c_maria", "session_end"); tool(client, "c_maria", "session_end")
    with session_scope() as s:
        assert s.get(CallSession, sid).ended_at is not None
        evs = [e for e in s.scalars(select(Event).where(Event.kind == "session.ended"))
               if e.payload["session_id"] == sid]
        assert len(evs) == 1

def test_session_start_supersedes_open_session(client):
    a = tool(client, "c_maria", "session_start")["session_id"]
    tool(client, "c_maria", "session_start")
    with session_scope() as s:
        ev = s.scalars(select(Event).where(Event.kind == "session.ended")).all()[-1]
        assert ev.payload == {"session_id": a, "reason": "superseded"}

def test_upload_during_session_records_session_id(client):
    client.post("/api/a/session", json={"token": "demo-ana"})
    png = (Path("seed/documents/ana_passport.png")).read_bytes()
    up = lambda: client.post("/api/a/documents", data={"document_type": "passport"},
                             files={"file": ("p.png", png, "image/png")}).json()
    outside = up()
    sid = tool(client, "c_ana", "session_start")["session_id"]
    inside = up()
    with session_scope() as s:
        assert s.get(Document, outside["id"]).session_id is None   # use the key the upload route returns
        assert s.get(Document, inside["id"]).session_id == sid

def test_voice_ws_disconnect_ends_session(client):
    client.post("/api/a/session", json={"token": "demo-maria"})
    with client.websocket_connect("/api/a/voice") as ws:
        ws.send_json({"type": "start", "mode": "text", "language": "en"})
        while ws.receive_json()["type"] != "ready":
            pass
    with session_scope() as s:
        assert all(x.ended_at for x in s.scalars(select(CallSession).where(CallSession.case_id == "c_maria")))
```

(`tool` and `H` are copied from `test_acceptance.py`; put shared helpers in `tests/conftest.py` if you need them in three or more files. If the TestClient websocket doesn't send the cookie jar, pass `headers={"cookie": ...}` built from `client.cookies`.)

- [ ] **Step 2: Run them and confirm they fail.** The upload test fails on the missing column, and the first two fail on the event count or reason. If `test_voice_ws_disconnect_ends_session` already passes, keep it as a regression guard: the observed open session was a tab that was still open.
- [ ] **Step 3: Implement `end_session`** in `case_service.py`. Then replace the three inline copies with it: `InProcessClient.session_end` uses `reason="liaison"`, the `/tools/session_end` route uses `"client"`, and the loop in `start_session` uses `"superseded"`.
- [ ] **Step 4: Fix `VoiceSession.shutdown`** so that, whenever `self.liaison` exists, it calls `self.liaison.c.session_end()`, dropping the `not self.liaison.ended` condition. This is safe because `end_session` is idempotent.
- [ ] **Step 5: Add `Document.session_id`** with its Postgres `ALTER`, thread `session_id` through `store_upload`, and in `applicant.upload` pass `active_session(s, case, None, create=False)`'s id or `None`. Staff uploads pass nothing.
- [ ] **Step 6: Run `uv run pytest` and confirm it passes**, including the existing AT tests.
- [ ] **Step 7: Commit** — `git commit -m "fix(sessions): single idempotent end_session; link uploads to the active session"`

### Task 4: Per-session summary artifact (F1)

**Files:**
- Modify: `backend/ellis/db.py` (new table `SessionArtifact`)
- Create: `backend/ellis/services/session_files.py`
- Modify: `backend/ellis/services/case_service.py` (`end_session` calls the builder)
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces the table `session_artifact`: `id` (`new_id("sa")`), `clinic_id`, `case_id` (indexed), `session_id` (indexed), `kind` String(40) = `"session_summary"`, `filename` = `"session_summary.pdf"`, `storage_path`, `sha256`, `ts`.
- Produces: `build_session_summary(s: Session, case: Case, sess: CallSession) -> SessionArtifact | None`. It writes `files_dir/<case_id>/sessions/<session_id>/session_summary.pdf` using `ellis.packet.builder.Pdf`. It returns `None`, and writes nothing, when the session has no applicant utterances, no facts with `provenance["session_id"] == sess.id`, and no documents with `session_id == sess.id`.
- PDF content, in the case language (`cs.case_lang(case)`). Title: "Session summary" / "Resumen de la sesión". Subtitle: name · date · channel · duration. Section "What you told us" / "Lo que nos dijo": the facts from this session that are not superseded and whose value is not `catalog.DEFERRED`. Vault fields render as `•••• <last4>` via `cs.vault_last4`, and everything else uses `display_value`. Section "Documents you shared" / "Documentos que compartió": document label and time. Never include the transcript, flags, or `[STOP:` text.
- `end_session` calls `build_session_summary` after setting `ended_at`. It catches and logs any exception: a failed summary must never block ending the session.

- [ ] **Step 1: Write the failing tests**

```python
def test_session_summary_built_on_end(client):
    sid = tool(client, "c_maria", "session_start")["session_id"]
    maria_trip(client)                       # copy from test_acceptance.py
    tool(client, "c_maria", "session_end")
    with session_scope() as s:
        arts = s.scalars(select(SessionArtifact).where(SessionArtifact.session_id == sid)).all()
        assert len(arts) == 1
        data = Path(arts[0].storage_path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == arts[0].sha256
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
    assert "2023" in text and "[STOP" not in text

def test_empty_session_builds_nothing(client):
    sid = tool(client, "c_rosa", "session_start")["session_id"]
    tool(client, "c_rosa", "session_end")
    with session_scope() as s:
        assert s.scalars(select(SessionArtifact).where(SessionArtifact.session_id == sid)).first() is None

def test_summary_omits_stop_now_and_vault_digits(client):
    # session + consent, then the stop-list turn used in test_at8 via /tools/applicant_turn,
    # then the A-number via /api/a/secure as in test_at9; end the session.
    ...
    assert "[STOP" not in text and "arrest" not in text.lower()
    assert A_NUMBER_DIGITS not in text      # the full number typed in the test
```

- [ ] **Step 2: Run them and confirm they fail** (the table is missing).
- [ ] **Step 3: Add the table and `session_files.py`, then call the builder from `end_session`.**
- [ ] **Step 4: Run `uv run pytest tests/test_storage.py` and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(sessions): build a session summary PDF when a session ends"`

### Task 5: Unified files API with kind-bound signed URLs (F1, F3)

**Files:**
- Modify: `backend/ellis/services/views.py` (add `case_files`)
- Modify: `backend/ellis/api/routes/applicant.py` (signed URLs, files route, `GET /api/a/files`)
- Modify: `backend/ellis/api/routes/clinic.py` (`GET /api/clinic/cases/{case_id}/files`; `case_packet` uses the new `signed_url`)
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces: `case_files(s: Session, case: Case, audience: Literal["clinic", "applicant"]) -> list[dict]`, sorted by `ts`. Each item is `{"id", "source": "document"|"packet"|"session", "kind", "filename", "session_id", "status", "sha256", "ts"}`.
  - applicant: all of this case's documents; packets with `status == "current"` and `kind != "reviewer_summary"`; all session artifacts.
  - clinic: all documents, all packets (any status), all session artifacts.
  - Packet `session_id` is `None`. Document `kind` = `document_type`.
- Produces: `signed_url(kind: Literal["packet","document","session"], obj_id: str, ttl_s: int = 900) -> str`, which returns `/files/{kind}/{obj_id}?exp=…&sig=…` with HMAC input `f"{kind}:{obj_id}:{exp}"`. Also `check_signed(kind, obj_id, exp, sig) -> bool`. Update every existing caller of `signed_url(p.id)`.
- Produces: `GET /files/{kind}/{obj_id}` (replaces `/files/packet/{packet_id}`). It resolves the row by kind, returns 404 if missing, and serves `Document.mime` for documents and `application/pdf` otherwise.
- Produces: `GET /api/a/files` → `{"files": [... + "url"]}`, and `GET /api/clinic/cases/{case_id}/files` (roles `ALL`, scoped by `clinic_case`) → the same shape.

- [ ] **Step 1: Write the failing tests**

```python
def test_applicant_files_hide_reviewer_summary_and_other_cases(client):
    sign_maria(client)                    # factor out of test_at15's setup
    files = client.get("/api/a/files").json()["files"]
    assert "reviewer_summary" not in {f["kind"] for f in files}
    assert {f["source"] for f in files} >= {"document", "packet"}
    for f in files:
        assert client.get(f["url"]).status_code == 200

def test_clinic_files_include_stale_and_reviewer_summary(client): ...
    # sign, invalidate (change a fact as in test_at16), sign again; clinic list has stale rows + reviewer_summary

def test_superseded_packet_url_serves_original_bytes(client): ...
    # url for a packet row, rebuild, GET old url → bytes hash == old row sha256

def test_signed_url_kind_cannot_be_swapped(client):
    url = client.get("/api/a/files").json()["files"][0]["url"]     # any packet url
    assert client.get(url.replace("/packet/", "/document/")).status_code == 403

def test_cross_clinic_files_404(client):
    client.post("/api/clinic/login", json={"email": "staff@other.demo", "password": "ellis-demo"})
    assert client.get("/api/clinic/cases/c_maria/files").status_code == 404
```

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement `case_files`, the kind-aware signing, the file route and the two list endpoints.**
- [ ] **Step 4: Run `uv run pytest` and confirm everything passes** (the AT15/AT16 packet tests use the new URL shape).
- [ ] **Step 5: Commit** — `git commit -m "feat(files): one files list per audience with kind-bound signed URLs"`

### Task 6: Files in both UIs

**Files:**
- Modify: `frontend/src/clinic/CaseDetail.tsx` (add `'Files'` to `TABS`, plus a `Files` component)
- Create: `frontend/src/applicant/Files.tsx`
- Modify: `frontend/src/applicant/ApplicantApp.tsx` (`Progress`, line ~297: render `<YourFiles lang={…} />`)

**Interfaces:**
- Consumes: `GET /api/clinic/cases/{id}/files` and `GET /api/a/files` (Task 5).
- Produces: `export function YourFiles({ lang }: { lang: Lang })`.
- Clinic `Files` groups items by `session_id`. Each group heading shows the session start time looked up from `d.events` (`session.started` payload); `null` goes under "Outside a session". Each row is a filename link (`window.open(url)`), source, kind, status and time. Stale packets show their status.
- Applicant `YourFiles` lists the same items without status. Heading: "Your files" / "Sus archivos". Empty state: "Files from your sessions will appear here." / "Aquí aparecerán los archivos de sus sesiones."

- [ ] **Step 1: Implement both components.**
- [ ] **Step 2: Type-check** — `cd frontend && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 3: Verify in the running app.** Start `./scripts/dev.sh`. As María (`/a/demo-maria`) do a text session, give one answer and end it. As Dana (`dana@valle.demo` / `ellis-demo`), confirm the Files tab shows the session group with `session_summary.pdf` and that it opens. Confirm the applicant Progress screen lists it too.
- [ ] **Step 4: Commit** — `git commit -m "feat(ui): files tab for clinic, your-files list for applicant"`

---

## Part B — Both Cartesia paths persist everything

### Task 7: Record voice fallback and the actual channel (F8)

**Files:**
- Modify: `backend/ellis/api/routes/voice.py` (`VoiceSession.run`)
- Modify: `frontend/src/applicant/voice.ts` (`start`: add `reason: 'mic_denied'` to the start message when the mic fails)
- Test: `backend/tests/test_voice_paths.py`

**Interfaces:**
- Produces the event `session.voice_unavailable`, payload `{"session_id", "reason"}`, where reason ∈ `{"no_api_key", "connect_failed", "mic_denied"}`, actor `system`/`gateway`. It is emitted once per session when voice was requested (or the start message carried `reason: "mic_denied"`) and the session runs as text.
- Produces: `CallSession.channel` is set to the actual `self.mode` (`"voice"` or `"text"`) after the Cartesia attempt.

- [ ] **Step 1: Write the failing test**

```python
def test_voice_without_key_records_fallback(client):
    client.post("/api/a/session", json={"token": "demo-maria"})
    with client.websocket_connect("/api/a/voice") as ws:
        ws.send_json({"type": "start", "mode": "voice", "language": "en"})
        ready = next(m for m in iter(ws.receive_json, None) if m["type"] == "ready")
    assert ready["mode"] == "text"
    with session_scope() as s:
        ev = s.scalars(select(Event).where(Event.kind == "session.voice_unavailable")).one()
        assert ev.payload["reason"] == "no_api_key"
        assert s.get(CallSession, ev.payload["session_id"]).channel == "text"
```

- [ ] **Step 2: Run it and confirm it fails.**
- [ ] **Step 3: Implement it** with `session_scope()` + `cs.emit`, using `self.liaison.c.session_id`.
- [ ] **Step 4: Run it and confirm it passes**, then run `cd frontend && npx tsc --noEmit`.
- [ ] **Step 5: Commit** — `git commit -m "fix(voice): record why a session fell back to text and the channel actually used"`

### Task 8: Line agent persists the full transcript and ends sessions (F5, F6, F7)

**Files:**
- Modify: `backend/ellis/config.py` (add `public_api_url`)
- Modify: `backend/ellis/voice/line_app.py`
- Modify: `backend/ellis/voice/client.py` (`HttpClient.read_back`, `HttpClient.liaison_said`)
- Modify: `backend/ellis/api/routes/tools.py` (`ReadBack.lang`, `SaidReq.meta`, and caption push in `liaison_said`)
- Modify: `backend/.env.example` (add `ELLIS_PUBLIC_API_URL=`)
- Test: `backend/tests/test_line_app.py`, `backend/tests/test_voice_paths.py`

**Interfaces:**
- Produces: `settings.public_api_url -> str`, from env `ELLIS_PUBLIC_API_URL`, default `"http://localhost:8000"`, with no trailing slash. Task 12 consumes it.
- `line_app.API = settings.public_api_url` and `SECRET = settings.tool_secret`. The `ELLIS_API_URL` env var is removed. On import, if the API host is `localhost` or `127.0.0.1`, log one warning: `"ELLIS_PUBLIC_API_URL is %s; a Cartesia-hosted agent cannot reach it. Use a public or tunneled URL."`
- `KeywordGuard.process` behavior:
  - On every `UserTurnEnded`, call `client.applicant_turn(text)` exactly once (the stop and sensitive branches already do; the normal branch now does too, before delegating).
  - For every `AgentSendText` the inner agent yields, call `client.liaison_said(out.text)` before yielding it.
  - On `CallEnded`, delegate, then call `client.session_end()`.
  - `ScriptedLineAgent` is unchanged, because `Liaison` already does all three.
- `HttpClient.read_back(field, read_value=None, briefing_version=None, lang="es")` sends `lang`. `ReadBack` gets `lang: str = "es"`, which is passed to `cs.read_back(..., lang=body.lang)`.
- `HttpClient.liaison_said(text, locked=False, meta=None)` sends `meta`. `SaidReq` gets `meta: dict | None = None`. The route stores the meta and calls `cs.push(s, case, "caption", {"speaker": "liaison", "text": body.text, "locked": body.locked})`, the same as `InProcessClient.liaison_said`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_line_app.py
line = pytest.importorskip("line")

class FakeClient:
    def __init__(self): self.calls = []
    def applicant_turn(self, t): self.calls.append(("applicant_turn", t)); return {}
    def liaison_said(self, t, locked=False, meta=None): self.calls.append(("liaison_said", t))
    def session_end(self): self.calls.append(("session_end",))
    def request_secure_entry(self, f): self.calls.append(("secure", f))

class Inner:
    history = None
    async def process(self, env, event):
        yield AgentSendText(text="Hola")

def run(guard, event):
    async def go(): return [o async for o in guard.process(None, event)]
    return asyncio.run(go())

def test_every_turn_and_line_is_recorded():
    c = FakeClient(); g = KeywordGuard(Inner(), c)
    run(g, user_turn("vivo en Fresno"))         # helper builds UserTurnEnded per line's constructor
    assert c.calls == [("applicant_turn", "vivo en Fresno"), ("liaison_said", "Hola")]

def test_call_end_closes_session():
    c = FakeClient(); g = KeywordGuard(Inner(), c)
    run(g, CallEnded()); assert c.calls[-1] == ("session_end",)

def test_stop_turn_never_reaches_inner():
    c = FakeClient(); g = KeywordGuard(Inner(), c)
    out = run(g, user_turn(STOP_PHRASE))         # the phrase test_at8 uses
    assert ("liaison_said", "Hola") not in c.calls and len(out) == 1
```

```python
# tests/test_voice_paths.py
def test_tools_liaison_said_pushes_caption(client, monkeypatch):
    pushed = []
    monkeypatch.setattr(cs, "push", lambda s, case, kind, p: pushed.append((kind, p)))
    tool(client, "c_maria", "session_start")
    tool(client, "c_maria", "liaison_said", {"text": "Hi", "meta": {"k": 1}})
    assert ("caption", {"speaker": "liaison", "text": "Hi", "locked": False}) in pushed

def test_tools_read_back_forwards_lang(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(cs, "read_back", lambda *a, **k: seen.update(k) or {"ok": True})
    tool(client, "c_maria", "read_back", {"field": "lpr_since", "lang": "en"})
    assert seen["lang"] == "en"
```

- [ ] **Step 2: Run them and confirm they fail** — `uv run --extra line pytest tests/test_line_app.py -v` and `uv run pytest tests/test_voice_paths.py -v`.
- [ ] **Step 3: Implement everything listed in Interfaces.**
- [ ] **Step 4: Run both commands again and confirm they pass.**
- [ ] **Step 5: Commit** — `git commit -m "fix(line): persist every turn and line, end sessions, use public API URL and settings secret"`

---

## Part C — Creao staff agents, our tools, external MCPs

### Design (read before Tasks 9–15)

```
Event ─▶ Runner.wakes() ─▶ Job(queued) ─▶ claim ─▶ CreaoBackend.dispatch ── POST /v1/runs ──▶ Creao
                                                     Job.status = "dispatched", staged={"items": []}
Creao agent ── MCP (Streamable HTTP, Bearer ELLIS_MCP_TOKEN_<AGENT>) ──▶ /mcp/<agent>/
     tools/list  → registry.tools_for(agent)
     tools/call  → registry.call(agent, name, args)  ──▶ runs.resolve_run(run_id, agent)  (scope = job's case)
                    ├─ read:            get_case, rules_engine             → masked context
                    ├─ propose:         propose_<item_type>                → runs.stage (authority pre-check)
                    ├─ external_read:   e.g. email_search                  → connectors.REMOTE_CALL → redacted
                    ├─ external_action: e.g. email_send                    → OutboundAction(pending) only
                    └─ finish_run                                          → runs.finalize → validate_envelope
                                                                              → apply_proposal(backend="creao")
Creao webhook /webhooks/creao ─▶ runs.finalize(run_id, "webhook")  (idempotent; failed status → job failed)
Runner.loop ─▶ runs.expire_dispatched()  (no finish in 15 min → failed, nothing written, board task)
Reviewer ─▶ POST /api/clinic/actions/{id}/decision ─▶ connectors.execute_action ─▶ external MCP
```

Decisions this plan locks in:

- **One MCP endpoint per role, not one shared endpoint.** Each role's server lists only its own tools and checks its own token, so a leaked paralegal token can't even see `propose_briefing`.
- **Case scope comes from `run_id`, never from a `case_id` argument.** Creao registers a static bearer token per MCP connection, and per-run tokens can't be injected. So every tool takes the `run_id` the dispatcher passed in, and `resolve_run` maps it to that job's case. Run ids are 24 hex characters and stop working once the run is done or expired.
- **Writes are staged, then applied once.** `apply_proposal` dedupes by `run_id`, so applying item by item would drop every item after the first. Staging keeps one envelope per run, preserves the existing dedupe, the stale-briefing check and "invalid output writes nothing", and still gives the agent immediate authority errors.
- **External MCPs are proxied through our server.** Creao agents must not connect to Gmail or any other MCP directly; their charters say so. Proxying gives role scoping, the work log (`tool.called` events), number redaction on reads, and the reviewer approval gate on sends.
- **Tools are framework-agnostic.** `registry.call` is plain Python. MCP is one adapter over it, so tests, an eventual local tool-use backend and Creao all run the same code.

### Task 9: Staff-tool registry and run staging

**Files:**
- Create: `backend/ellis/staff_tools/__init__.py` (empty until Task 10)
- Create: `backend/ellis/staff_tools/registry.py`
- Create: `backend/ellis/staff_tools/runs.py`
- Modify: `backend/ellis/db.py` (`Job.staged: JSONType, default=dict`, plus a Postgres `ALTER`)
- Modify: `backend/ellis/agents/proposals.py` (extract `authority_reason`)
- Modify: `backend/ellis/agents/runner.py` (`claim`: `run_{secrets.token_hex(12)}`)
- Test: `backend/tests/test_staff_tools.py`

**Interfaces:**
- Produces in `registry.py`:

```python
ToolKind = Literal["read", "propose", "external_read", "external_action"]

class RunArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str

@dataclass(frozen=True)
class RunCtx:
    run_id: str; agent: str; case_id: str; clinic_id: str; job_id: int

@dataclass(frozen=True)
class StaffTool:
    name: str; description: str; kind: ToolKind; roles: frozenset[str]
    input_model: type[RunArgs]
    handler: Callable[[Session, RunCtx, RunArgs], dict]

class ToolError(Exception):
    def __init__(self, code: str, message: str): ...   # .code, .message

REGISTRY: dict[str, StaffTool]
def register(tool: StaffTool) -> StaffTool            # ValueError on duplicate name
def tools_for(role: str) -> list[StaffTool]           # sorted by name
def call(role: str, name: str, args: dict) -> dict
```

  `call` raises `ToolError("unknown_tool")` when `name` isn't in `tools_for(role)`, and `ToolError("invalid_args", <pydantic message ≤500 chars>)` when the args don't validate. Otherwise it opens `session_scope()`, runs `ctx = runs.resolve_run(s, run_id, role)`, then the handler, and returns the result. It always emits `tool.called` with payload `{"tool", "run_id", "agent", "ok", "ms", "error_code"}`, actor_type `"agent"`, actor `f"{role}@{run_id}"`. On failure it emits from a fresh `session_scope()`, because the failed one rolls back. If the case is unknown, it emits with `case=None`.
- Produces in `runs.py`:

```python
RUN_TTL_S = 900
def resolve_run(s: Session, run_id: str, role: str) -> RunCtx
    # Job with run_id, agent == role, status == "dispatched", claimed_at within RUN_TTL_S; else ToolError("run_not_active")
def stage(s: Session, ctx: RunCtx, item_type: str, payload: dict) -> dict
    # PAYLOADS[item_type].model_validate (ToolError "invalid_payload"); authority_reason → ToolError("outside_authority", reason)
    # appends {"type", "payload"} to job.staged["items"] (reassign the dict so SQLAlchemy sees the change); returns {"staged": len(items)}
def finalize(s: Session, run_id: str, source: Literal["finish_run", "webhook"]) -> dict
    # job.status done → {"duplicate": True}; job not dispatched → ToolError("run_not_active")
    # Envelope(agent, run_id, case_id, based_on_event_id=staged.get("based_on_event_id"), items) → validate_envelope
    # → apply_proposal(s, env, backend="creao", trigger_events=job.trigger_events); job.status="done", finished_at=now()
    # returns apply_proposal's result
def expire_dispatched(max_age_s: int = RUN_TTL_S) -> int
    # dispatched jobs with claimed_at older than max_age_s → failed via the same writes as Runner._fail
    # (AgentRun failed, board Task "Agent did not finish (<agent>): nothing was written", agent.run_failed event); returns count
```
- Produces in `proposals.py`: `authority_reason(agent: str, item_type: str, payload: BaseModel) -> str | None`. It returns the rejection reason for the static checks (type not in authority, task kind, memo kind, review category) using the exact reason strings `apply_proposal` uses today. `apply_proposal` calls it instead of its inline checks, and the session-dependent checks (stop fields, duplicates, challenge rounds, staleness) stay in `apply_proposal`.
- Test helper (in `tests/conftest.py`): `dispatched_job(case_id: str, agent: str) -> str`. It inserts a `Job(status="dispatched", run_id=f"run_{secrets.token_hex(12)}", claimed_at=now(), staged={"items": []}, trigger_events=[])` and returns its run_id.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture()
def clean_registry():
    saved = dict(registry.REGISTRY); yield; registry.REGISTRY.clear(); registry.REGISTRY.update(saved)

def test_tools_for_role_lists_only_that_roles_tools(clean_registry):
    registry.register(StaffTool("only_qa", "x", "read", frozenset({"qa_reviewer"}), RunArgs, lambda s, c, a: {}))
    assert "only_qa" in [t.name for t in registry.tools_for("qa_reviewer")]
    assert "only_qa" not in [t.name for t in registry.tools_for("case_manager")]
    with pytest.raises(ToolError) as e: registry.call("case_manager", "only_qa", {"run_id": "x"})
    assert e.value.code == "unknown_tool"

def test_call_rejects_run_of_other_role(seeded, clean_registry):
    rid = dispatched_job("c_maria", "doc_paralegal")
    registry.register(StaffTool("ping", "x", "read", frozenset({"case_manager"}), RunArgs, lambda s, c, a: {"ok": 1}))
    with pytest.raises(ToolError) as e: registry.call("case_manager", "ping", {"run_id": rid})
    assert e.value.code == "run_not_active"
    with session_scope() as s:
        ev = s.scalars(select(Event).where(Event.kind == "tool.called")).all()[-1]
        assert ev.payload["ok"] is False and "args" not in ev.payload

def test_call_rejects_finished_or_expired_run(seeded, clean_registry): ...
    # status "done" → run_not_active; claimed_at = now() - 901s → run_not_active

def test_stage_rejects_outside_authority(seeded):
    rid = dispatched_job("c_maria", "docketing_clerk")
    with session_scope() as s:
        ctx = runs.resolve_run(s, rid, "docketing_clerk")
        with pytest.raises(ToolError) as e: runs.stage(s, ctx, "memo", {"kind": "qa", "body_md": "x"})
        assert e.value.code == "outside_authority"
        assert s.scalars(select(Job).where(Job.run_id == rid)).one().staged["items"] == []

def test_finalize_applies_once(seeded):
    rid = dispatched_job("c_maria", "case_manager")
    with session_scope() as s:
        ctx = runs.resolve_run(s, rid, "case_manager")
        runs.stage(s, ctx, "task", {"kind": "finding", "title": "A"})
        runs.stage(s, ctx, "task", {"kind": "question", "title": "B"})
        runs.finalize(s, rid, "finish_run")
    with session_scope() as s:
        assert runs.finalize(s, rid, "webhook") == {"duplicate": True}
        assert {t.title for t in s.scalars(select(Task).where(Task.proposed_by == f"case_manager@{rid}"))} == {"A", "B"}

def test_expire_dispatched_writes_nothing(seeded): ...
    # stage a task, age claimed_at past TTL, expire_dispatched() == 1, job failed, no Task titled "A", board task exists
```

- [ ] **Step 2: Run `uv run pytest tests/test_staff_tools.py -v` and confirm it fails.**
- [ ] **Step 3: Implement `authority_reason`**, then run `uv run pytest tests/test_acceptance.py -k authority`. Expected: PASS, unchanged behavior.
- [ ] **Step 4: Implement `registry.py`, `runs.py`, `Job.staged` and the longer run ids.**
- [ ] **Step 5: Run `uv run pytest` and confirm everything passes.**
- [ ] **Step 6: Commit** — `git commit -m "feat(staff-tools): role-scoped tool registry with staged, apply-once agent runs"`

### Task 10: Case tools: read, propose, finish

**Files:**
- Create: `backend/ellis/staff_tools/case_tools.py`
- Modify: `backend/ellis/staff_tools/__init__.py` (`from . import case_tools  # noqa: F401`)
- Test: `backend/tests/test_staff_tools.py`

**Interfaces:**
- Consumes: `registry.register`, `RunArgs`, `runs.stage`, `runs.finalize` (Task 9); `build_context` (`agents/context.py`); `fresh_recompute` (`agents/backends.py`); `PAYLOADS`, `AUTHORITY` (`agents/proposals.py`).
- Produces these registered tools:
  - `get_case` (read, all four roles). Returns `build_context(s, case, job.trigger_events)` and records `job.staged["based_on_event_id"] = ctx["latest_event_id"]`, so staleness is measured from what the agent actually read.
  - `rules_engine` (read, `docketing_clerk`, `qa_reviewer`). Returns `fresh_recompute(build_context(...))`.
  - `propose_<item_type>` for every key in `PAYLOADS` (kind `propose`). Roles are `{a for a, auth in AUTHORITY.items() if item_type in auth["types"]}`. The input model is `create_model(f"Propose_{item_type}", __base__=RunArgs, payload=(PAYLOADS[item_type], ...))`. The handler calls `runs.stage(s, ctx, item_type, args.payload.model_dump())`. Each description is one line ending in `"Staged; applied when you call finish_run."`
  - `finish_run` (kind `propose`, all roles). Input is `RunArgs` plus `summary: str = Field("", max_length=500)`. It returns `runs.finalize(s, ctx.run_id, "finish_run")`.
- Move `EXPECTED` into `tests/conftest.py`; Tasks 11 and 15 reuse it.
- Deliberately skipped: the spec's `list_tasks`, `list_documents` and `compare_fact_to_doc` (`get_case` already returns tasks, documents and extractions), `fill_n400` (packets build only at sign-off) and `policy_lookup` (no policy source exists yet). Add them as registry tools when a charter needs them.

- [ ] **Step 1: Write the failing tests**

```python
EXPECTED = {
    "case_manager": {"get_case", "finish_run", "propose_briefing", "propose_task", "propose_memo", "propose_review_item"},
    "doc_paralegal": {"get_case", "finish_run", "propose_gap", "propose_gap_close", "propose_task",
                      "propose_review_item", "propose_evidence", "propose_doc_checks"},
    "docketing_clerk": {"get_case", "finish_run", "rules_engine", "propose_deadline", "propose_task"},
    "qa_reviewer": {"get_case", "finish_run", "rules_engine", "propose_task", "propose_review_item",
                    "propose_memo", "propose_review_note"},
}

def test_role_tool_sets_match_spec():
    import ellis.staff_tools  # noqa: F401   (no connector env set in tests → no connector tools)
    for role, names in EXPECTED.items():
        assert {t.name for t in registry.tools_for(role)} == names, role
    assert not any(w in n for n in registry.REGISTRY for w in ("approve", "sign", "file_", "submit_packet"))

def test_get_case_is_masked(client):
    # set A-number via /api/a/secure as in test_at9 (digits A_NUMBER_DIGITS)
    rid = dispatched_job("c_maria", "case_manager")
    out = json.dumps(registry.call("case_manager", "get_case", {"run_id": rid}))
    assert A_NUMBER_DIGITS not in out and catalog.mask_token("a_number") in out

def test_skeleton_output_through_tools_publishes_briefing(seeded):
    rid = dispatched_job("c_maria", "case_manager")
    ctx = registry.call("case_manager", "get_case", {"run_id": rid})
    for it in skeleton.AGENTS["case_manager"](ctx):
        registry.call("case_manager", f"propose_{it['type']}", {"run_id": rid, "payload": it["payload"]})
    before = latest_briefing_version("c_maria")
    res = registry.call("case_manager", "finish_run", {"run_id": rid})
    assert res.get("rejected") == [] and latest_briefing_version("c_maria") >= before
```

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement `case_tools.py`.**
- [ ] **Step 4: Run `uv run pytest tests/test_staff_tools.py` and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(staff-tools): case read, propose and finish tools generated from the proposal schema"`

### Task 11: MCP server per role on the Case API

**Files:**
- Modify: `backend/pyproject.toml` (add `"mcp>=1.12"` to dependencies), then run `uv lock`
- Create: `backend/ellis/staff_tools/mcp_server.py`
- Modify: `backend/ellis/api/app.py` (mount the apps and enter their managers in `lifespan`)
- Modify: `backend/ellis/api/app.py` `NoToolBodies` filter so it also covers `/mcp/`
- Modify: `backend/.env.example` (`ELLIS_MCP_TOKEN_CASE_MANAGER=` and the same for `DOC_PARALEGAL`, `DOCKETING_CLERK`, `QA_REVIEWER`)
- Test: `backend/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `registry.tools_for`, `registry.call`, `ToolError` (Task 9).
- Produces:

```python
ROLES: tuple[str, ...] = tuple(AUTHORITY)                  # the four agent names
def role_token(role: str) -> str | None                     # os.environ.get(f"ELLIS_MCP_TOKEN_{role.upper()}") or None
def build_server(role: str) -> mcp.server.lowlevel.Server
    # list_tools → [types.Tool(name, description, inputSchema=t.input_model.model_json_schema()) for t in tools_for(role)]
    # call_tool(name, arguments) → [types.TextContent(type="text", text=json.dumps(registry.call(role, name, arguments), default=str))]
    #   (registry.call is sync and does DB work: run it via anyio.to_thread.run_sync)
    # ToolError → raise ValueError(f"{e.code}: {e.message}") so the SDK returns isError=True with that text
class RoleMCPApp:                                            # ASGI
    def __init__(self, role: str, manager: StreamableHTTPSessionManager): ...
    async def __call__(self, scope, receive, send):
        # no role_token → 503 {"error":{"code":"not_configured"}}; header mismatch (hmac.compare_digest) → 401
        # else await manager.handle_request(scope, receive, send)
def mcp_managers() -> dict[str, StreamableHTTPSessionManager]
    # one StreamableHTTPSessionManager(app=build_server(r), stateless=True, json_response=True) per role
```

- In `create_app`: build `managers = mcp_managers()` inside `create_app` (a manager's `run()` can be entered only once per instance, and tests create many apps). Do `app.mount(f"/mcp/{role}", RoleMCPApp(role, managers[role]))` for each role, and in `lifespan` enter every `manager.run()` with a `contextlib.AsyncExitStack` around the existing `yield`.
- The MCP URL to register in Creao is `{ELLIS_PUBLIC_API_URL}/mcp/<agent>/`, with the trailing slash. Without it, Starlette's Mount redirects.
- Known SDK gotcha: if requests come back `421 Misdirected Request`, that's the SDK's DNS-rebinding protection. Pass `security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False)` to the manager. Bearer auth is the guard.

- [ ] **Step 1: Write the failing tests**

```python
MCP_H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
         "MCP-Protocol-Version": "2025-06-18"}
INIT = {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}}

def rpc(c, role, method, params, token, id=1):
    return c.post(f"/mcp/{role}/", json={"jsonrpc": "2.0", "id": id, "method": method, "params": params},
                  headers={**MCP_H, "Authorization": f"Bearer {token}"})

@pytest.fixture()
def tokens(monkeypatch):
    for r in ROLES: monkeypatch.setenv(f"ELLIS_MCP_TOKEN_{r.upper()}", f"tok-{r}")

def test_mcp_requires_role_token(client, monkeypatch):
    assert rpc(client, "case_manager", "initialize", INIT, "x").status_code == 503
    monkeypatch.setenv("ELLIS_MCP_TOKEN_CASE_MANAGER", "tok")
    assert rpc(client, "case_manager", "initialize", INIT, "wrong").status_code == 401

def test_mcp_token_of_one_role_rejected_on_another(client, tokens):
    assert rpc(client, "case_manager", "initialize", INIT, "tok-qa_reviewer").status_code == 401

def test_mcp_lists_only_role_tools(client, tokens):
    assert rpc(client, "docketing_clerk", "initialize", INIT, "tok-docketing_clerk").status_code == 200
    r = rpc(client, "docketing_clerk", "tools/list", {}, "tok-docketing_clerk", id=2).json()
    assert {t["name"] for t in r["result"]["tools"]} == EXPECTED["docketing_clerk"]   # import from test_staff_tools

def test_mcp_call_tool_round_trip(client, tokens):
    rid = dispatched_job("c_maria", "case_manager")
    r = rpc(client, "case_manager", "tools/call", {"name": "get_case", "arguments": {"run_id": rid}},
            "tok-case_manager", id=3).json()
    assert json.loads(r["result"]["content"][0]["text"])["case"]["id"] == "c_maria"

def test_mcp_tool_error_is_reported_not_raised(client, tokens):
    r = rpc(client, "case_manager", "tools/call", {"name": "get_case", "arguments": {"run_id": "run_nope"}},
            "tok-case_manager").json()
    assert r["result"]["isError"] is True and "run_not_active" in r["result"]["content"][0]["text"]
```

Put `MCP_H`, `INIT`, `rpc` and the `tokens` fixture in `tests/conftest.py`; Task 15 reuses them.

- [ ] **Step 2: Run `uv sync && uv run pytest tests/test_mcp_server.py -v` and confirm it fails** (404 on `/mcp/...`).
- [ ] **Step 3: Implement `mcp_server.py` and the `create_app` wiring.**
- [ ] **Step 4: Run `uv run pytest` and confirm everything passes.**
- [ ] **Step 5: Commit** — `git add backend/pyproject.toml backend/uv.lock ...` then `git commit -m "feat(mcp): role-scoped MCP server for Creao staff agents"`

### Task 12: Creao run lifecycle in the runner and webhook

**Files:**
- Modify: `backend/ellis/agents/backends.py` (`CreaoBackend.dispatch`)
- Modify: `backend/ellis/agents/runner.py` (`run_job` async branch, `loop` expiry sweep)
- Modify: `backend/ellis/api/routes/webhooks.py`
- Modify: `backend/.env.example` (`CREAO_AGENT_CASE_MANAGER=` and the same for `DOC_PARALEGAL`, `DOCKETING_CLERK`, `QA_REVIEWER`)
- Test: `backend/tests/test_creao.py`

**Interfaces:**
- Consumes: `settings.public_api_url` (Task 8); `runs.finalize`, `runs.expire_dispatched` (Task 9).
- `CreaoBackend.dispatch(agent, case_id, reason, run_id) -> dict` posts `{"agent_id", "input": {"run_id", "case_id", "agent", "reason"}, "webhook_url": settings.public_api_url + "/webhooks/creao"}` and keeps `TODO(open-question-7)` on the field names.
- `Runner.run_job` async branch: before dispatching, set `staged = {"items": []}`. On success, set `status = "dispatched"` and leave `finished_at = None`. Don't call `_finish(job, "dispatched")`. On exception, call `_fail` (unchanged).
- `Runner.loop`: call `runs.expire_dispatched()` at most every 30 s (track `self._last_sweep`).
- Webhook, after signature check and delivery dedupe: `run_id = _run_id(body)`, which checks `body.get("run_id")`, then `body.get("input", {}).get("run_id")`, then the envelope's `run_id`, marked `TODO(open-question-7)`. Then schedule `_complete(body, run_id)` via FastAPI `BackgroundTasks`, replacing the raw thread. `_complete`:
  - If `body.get("status")` is `"failed"` or `"error"`, the job fails exactly as `expire_dispatched` does, with the title "Agent run failed in Creao (<agent>): nothing was written".
  - Else, if the envelope has `items` and the job is still dispatched, stage each item through `runs.stage`. Skip any item that raises `ToolError`, and emit `proposal.rejected` for it with payload `{"agent", "run_id", "type", "reason": e.code}`, the same shape `proposals._reject` uses. Then call `runs.finalize(s, run_id, "webhook")`.
  - `ToolError("run_not_active")` is swallowed: the run was already finished or expired.
- `_seen` stays as a fast path. Correctness comes from `finalize` being idempotent.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture()
def creao(monkeypatch):
    sent = []
    monkeypatch.setenv("CREAO_API_KEY", "cr_sk_test"); monkeypatch.setenv("CREAO_WEBHOOK_SECRET", "whs")
    for a in ROLES: monkeypatch.setenv(f"CREAO_AGENT_{a.upper()}", f"ag_{a}")
    monkeypatch.setattr(backends.httpx, "post", lambda url, **kw: sent.append(kw["json"]) or FakeResp({"id": "r1"}))
    return sent

class FakeResp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data

def hook(c, body, delivery="d1"):
    return c.post("/webhooks/creao", json=body, headers={"x-creao-signature": "whs", "x-creao-delivery-id": delivery})

def test_creao_dispatch_marks_job_dispatched(client, creao):
    r = Runner(backend=backends.CreaoBackend(), debounce_s=0); r.dispatch_new_events()
    consent(client); r.dispatch_new_events(); r.drain()
    assert creao and {"run_id", "case_id", "agent", "reason"} <= set(creao[0]["input"])
    with session_scope() as s:
        j = s.scalars(select(Job).where(Job.run_id == creao[0]["input"]["run_id"])).one()
        assert j.status == "dispatched" and j.staged == {"items": []} and j.finished_at is None

def test_webhook_without_finish_run_applies_staged(client, creao):
    rid = dispatched_job("c_maria", "case_manager")
    registry.call("case_manager", "propose_task", {"run_id": rid, "payload": {"kind": "finding", "title": "W"}})
    assert hook(client, {"run_id": rid, "status": "completed"}).status_code == 200
    assert task_titles(rid) == {"W"} and job_status(rid) == "done"

def test_webhook_after_finish_run_is_noop(client, creao):
    rid = dispatched_job("c_maria", "case_manager")
    registry.call("case_manager", "propose_task", {"run_id": rid, "payload": {"kind": "finding", "title": "W"}})
    registry.call("case_manager", "finish_run", {"run_id": rid})
    hook(client, {"run_id": rid, "status": "completed"}, "d2"); hook(client, {"run_id": rid}, "d3")
    assert task_titles(rid) == {"W"}

def test_webhook_failed_status_marks_job_failed_nothing_written(client, creao): ...

def test_runner_expires_stale_dispatch(seeded): ...
    # age a dispatched job past RUN_TTL_S; Runner(...)._sweep() (or expire_dispatched()) → failed + board task
```

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement the dispatch, runner and webhook changes.**
- [ ] **Step 4: Run `uv run pytest` and confirm everything passes**, including AT19 and AT20, which still use the synchronous backends.
- [ ] **Step 5: Commit** — `git commit -m "feat(creao): dispatched-run lifecycle with webhook completion and expiry"`

### Task 13: External tools and MCP connectors with an approval gate

**Files:**
- Create: `backend/config/connectors.yaml`
- Create: `backend/ellis/staff_tools/connectors.py`
- Modify: `backend/ellis/staff_tools/__init__.py` (after `case_tools`: `connectors.register_connector_tools()`)
- Modify: `backend/ellis/db.py` (new table `OutboundAction`)
- Modify: `backend/ellis/api/routes/clinic.py` (actions list and decision)
- Modify: `backend/.env.example` (`ELLIS_MCP_EMAIL_URL=`, `ELLIS_MCP_EMAIL_TOKEN=`)
- Test: `backend/tests/test_connectors.py`

**Interfaces:**
- `connectors.yaml` format (the shipped file):

```yaml
# External MCP servers reached only through Ellis (role-scoped, logged, redacted, approval-gated).
# A connector is skipped entirely when its url_env is empty.
email:
  url_env: ELLIS_MCP_EMAIL_URL
  token_env: ELLIS_MCP_EMAIL_TOKEN
  tools:
    - name: email_search            # the name Ellis agents see
      remote: search_emails         # TODO(connector-email): the tool name on the chosen email MCP server
      kind: external_read
      roles: [case_manager, doc_paralegal]
      description: "Search the clinic inbox for messages about this case (sender, subject, date). Read-only."
    - name: email_send
      remote: send_email            # TODO(connector-email)
      kind: external_action
      roles: [case_manager]
      description: "Draft an email for a reviewer to approve. Nothing is sent until a reviewer approves it."
```

- Produces `OutboundAction` (table `outbound_action`): `id` (`new_id("oa")`), `clinic_id`, `case_id` (indexed), `run_id`, `agent`, `connector`, `tool`, `remote_tool`, `args` JSON, `status` String(20) ∈ `pending|rejected|sent|failed`, `decided_by` nullable, `decided_at` nullable, `result` JSON default dict, `error` Text nullable, `ts`.
- Produces in `connectors.py`:

```python
@dataclass(frozen=True)
class ConnectorTool: name: str; remote: str; kind: Literal["external_read", "external_action"]; roles: frozenset[str]; description: str
@dataclass(frozen=True)
class Connector: name: str; url: str; token: str | None; tools: tuple[ConnectorTool, ...]

class ExternalArgs(RunArgs):
    args: dict[str, Any] = Field(default_factory=dict)

def load_connectors(path: Path = CONFIG_DIR / "connectors.yaml") -> list[Connector]
def remote_call(connector: Connector, remote_tool: str, args: dict) -> dict
    # asyncio.run over mcp.client.streamable_http.streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"})
    # + ClientSession.initialize() + call_tool(remote_tool, args); 20 s timeout
    # returns {"content": [<text of each TextContent>], "is_error": bool}
REMOTE_CALL: Callable[[Connector, str, dict], dict] = remote_call   # test seam; handlers call connectors.REMOTE_CALL
def register_connector_tools(connectors: list[Connector] | None = None) -> None
    # one StaffTool per ConnectorTool, input_model=ExternalArgs
    # external_read handler: REMOTE_CALL → every string run through keywords.redact_numbers → returned
    # external_action handler: OutboundAction(status="pending") + Task(kind="system", title=f"Approve outbound {tool} (proposed by {agent})")
    #   + event "action.proposed" {"action_id", "tool", "agent"}; returns {"action_id", "status": "pending_approval"}
def execute_action(s: Session, action: OutboundAction, staff: StaffUser) -> OutboundAction
    # status not in {"pending", "failed"} → CaseError("not_pending", ..., status=409)
    # REMOTE_CALL; ok → "sent", result = redacted output; exception or is_error → "failed", error = str(e)[:500]
    # decided_by/decided_at set; event "action.sent" | "action.failed" {"action_id"}, actor staff
```

- Produces clinic routes:
  - `GET /api/clinic/cases/{case_id}/actions` (roles `ALL`, `clinic_case` scope) → `{"actions": [{"id", "agent", "tool", "args", "status", "error", "ts", "decided_by"}]}`.
  - `POST /api/clinic/actions/{action_id}/decision`, body `{"approve": bool}`, roles `("reviewer", "admin")`, scoped with `clinic_case(s, u, action.case_id)`. Approve → `execute_action`. Reject → `status="rejected"` (409 if already sent or rejected). Returns the action row.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.fixture()
def email(monkeypatch, tmp_path, clean_registry):
    calls = []
    monkeypatch.setenv("ELLIS_MCP_EMAIL_URL", "https://mcp.example/email")
    monkeypatch.setattr(connectors, "REMOTE_CALL", lambda c, t, a: calls.append((t, a)) or {"content": ["ok"], "is_error": False})
    connectors.register_connector_tools()
    return calls

def test_connector_disabled_without_url(clean_registry, monkeypatch):
    monkeypatch.delenv("ELLIS_MCP_EMAIL_URL", raising=False); connectors.register_connector_tools()
    assert "email_send" not in registry.REGISTRY

def test_external_read_redacts_numbers(seeded, email, monkeypatch):
    monkeypatch.setattr(connectors, "REMOTE_CALL", lambda c, t, a: {"content": ["A# 123456789"], "is_error": False})
    rid = dispatched_job("c_maria", "case_manager")
    assert "123456789" not in json.dumps(registry.call("case_manager", "email_search", {"run_id": rid, "args": {"q": "x"}}))

def test_external_action_requires_approval(client, email):
    rid = dispatched_job("c_maria", "case_manager")
    aid = registry.call("case_manager", "email_send", {"run_id": rid, "args": {"to": "a@b.c"}})["action_id"]
    assert email == []
    client.post("/api/clinic/login", json={"email": "sam@valle.demo", "password": "ellis-demo"})
    assert client.post(f"/api/clinic/actions/{aid}/decision", json={"approve": True}).status_code == 403
    client.post("/api/clinic/login", json={"email": "dana@valle.demo", "password": "ellis-demo"})
    assert client.post(f"/api/clinic/actions/{aid}/decision", json={"approve": True}).json()["status"] == "sent"
    assert email == [("send_email", {"to": "a@b.c"})]
    assert client.post(f"/api/clinic/actions/{aid}/decision", json={"approve": True}).status_code == 409

def test_rejected_action_never_sent(client, email): ...
def test_failed_send_is_retryable(client, email, monkeypatch): ...
    # REMOTE_CALL raises → status "failed", error visible in GET actions; restore fake; approve again → "sent"
def test_connector_tool_respects_roles(seeded, email):
    rid = dispatched_job("c_maria", "qa_reviewer")
    with pytest.raises(ToolError) as e: registry.call("qa_reviewer", "email_send", {"run_id": rid, "args": {}})
    assert e.value.code == "unknown_tool"
def test_cross_clinic_cannot_decide_action(client, email): ...   # staff@other.demo → 404
```

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement the yaml, the table, `connectors.py`, the routes and the wiring.**
- [ ] **Step 4: Run `uv run pytest` and confirm everything passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(connectors): external MCP tools behind role scope, redaction and reviewer approval"`

### Task 14: Clinic approvals UI

**Files:**
- Modify: `frontend/src/clinic/CaseDetail.tsx` (add `'Approvals'` to `TABS`, plus an `Approvals` component)

**Interfaces:**
- Consumes: `GET /api/clinic/cases/{id}/actions`, `POST /api/clinic/actions/{id}/decision` (Task 13).
- Behavior: the tab label shows a pending count like the existing Review tab. Each row shows tool, agent, args (`<pre>{JSON.stringify(args, null, 2)}</pre>`), status, error and time. Approve and Reject buttons appear only when `me.role !== 'intake'` and status is `pending` or `failed`. After a decision, reload.

- [ ] **Step 1: Implement it.**
- [ ] **Step 2: Type-check** — `cd frontend && npx tsc --noEmit`. Expected: no errors.
- [ ] **Step 3: Verify in the browser.** With `ELLIS_MCP_EMAIL_URL` set and `REMOTE_CALL` pointed at nothing, create a pending action via `uv run python -c` calling `registry.call("case_manager","email_send",...)` on a `dispatched_job`. As Dana, approve it. The status changes to `failed` (unreachable) with the error shown. As Sam, no buttons are shown.
- [ ] **Step 4: Commit** — `git commit -m "feat(ui): clinic approvals tab for agent-proposed outbound actions"`

### Task 15: Charters, the handoff runbook, and a simulated Creao run

**Files:**
- Create: `backend/prompts/creao_contract.md`
- Create: `backend/ellis/agents/charters.py`
- Create: `docs/creao-integration.md`
- Test: `backend/tests/test_creao.py`

**Interfaces:**
- Consumes: `registry.tools_for` (Tasks 9–13).
- Produces: `charter_for(agent: str) -> str`. This is `prompts/<agent>.md` with its `## Output schema` section removed (that section is the JSON-envelope contract for `AnthropicBackend`, which stays as is), then the full text of `creao_contract.md`, then `## Your tools` with one line per tool, `- <name> (<kind>): <description>`, from `tools_for(agent)`. It also provides a CLI, `uv run python -m ellis.agents.charters <agent>`, that prints it.
- `creao_contract.md` must state these rules, wording up to the writer:
  1. Your run input has `run_id` and `case_id`. Pass `run_id` to every tool. Never invent one.
  2. Call `get_case` first.
  3. Make changes only through `propose_*` tools. Nothing is written until `finish_run`.
  4. Call `finish_run` exactly once, last, even if you propose nothing.
  5. `external_action` tools never send anything; they draft for a reviewer.
  6. Never use Creao's built-in web search or any connector other than the Ellis MCP server.
  7. Masked tokens like `[A_NUMBER]` stay masked. Never ask for or guess real identifiers.
  8. Your authority limits are enforced by the server: an `outside_authority` error means don't retry that item.
- `docs/creao-integration.md` sections, each filled in from this plan's final code:
  - **Architecture** — the diagram from Part C "Design".
  - **Environment** — a table: `CREAO_API_KEY`, `CREAO_BASE_URL`, `CREAO_AGENT_<AGENT>`, `CREAO_WEBHOOK_SECRET`, `ELLIS_AGENT_BACKEND=creao`, `ELLIS_PUBLIC_API_URL`, `ELLIS_MCP_TOKEN_<AGENT>`, `ELLIS_MCP_EMAIL_URL` and `_TOKEN`.
  - **Creating each Creao agent** — for each of the four: paste `charter_for(agent)`; register the MCP server `{ELLIS_PUBLIC_API_URL}/mcp/<agent>/` with bearer `ELLIS_MCP_TOKEN_<AGENT>`; disable built-in web search and other connectors; set the model per the spec table (case_manager Opus, doc_paralegal Sonnet, docketing_clerk Haiku, qa_reviewer Opus); record the agent id in `CREAO_AGENT_<AGENT>`; set the webhook secret.
  - **Exposing the dev server** — a tunnel, for example `cloudflared tunnel --url http://localhost:8000`, assigned to `ELLIS_PUBLIC_API_URL`. The same URL serves the Line agent.
  - **Adding a tool we write** — a 10-line `register(StaffTool(...))` example in a new module imported from `staff_tools/__init__.py`, covering choosing `kind` and `roles` and returning plain JSON.
  - **Adding an external MCP** — a `connectors.yaml` entry, env vars, a choice of `external_read` vs `external_action`, and the rule that sends always go through approval.
  - **Testing without credits** — `uv run pytest tests/test_creao.py::test_simulated_creao_run_end_to_end`.
  - **Open questions** — Creao `/v1/runs` field names and webhook body shape (`TODO(open-question-7)` in `backends.py` and `webhooks.py`); whether a custom MCP counts against the per-agent connector limit (`docs/oneshot.md` line ~1224); the email MCP's real tool names (`TODO(connector-email)`).
  - **Go-live checklist** — secrets set and not dev defaults; `/api/health` shows `agent_backend: creao`; one rehearsal run per agent visible as an `AgentRun` with `backend == "creao"`; an approvals tab round trip.

- [ ] **Step 1: Write the failing tests**

```python
def test_charter_lists_role_tools():
    c = charter_for("qa_reviewer")
    assert "rules_engine" in c and "finish_run" in c and "propose_briefing" not in c
    assert "Return ONLY a proposal envelope" not in c

def test_simulated_creao_run_end_to_end(client, creao, tokens):
    r = Runner(backend=backends.CreaoBackend(), debounce_s=0); r.dispatch_new_events()
    maria_trip(client)                                  # wakes several agents
    r.settle()
    assert creao, "nothing dispatched"
    for run in creao:                                   # act as Creao for every dispatched run, over HTTP MCP
        a, rid = run["input"]["agent"], run["input"]["run_id"]; tok = f"tok-{a}"
        rpc(client, a, "initialize", INIT, tok)
        ctx = json.loads(rpc(client, a, "tools/call", {"name": "get_case", "arguments": {"run_id": rid}}, tok)
                         .json()["result"]["content"][0]["text"])
        items = skeleton.AGENTS[a](ctx, recompute=lambda: {}) if a == "qa_reviewer" else skeleton.AGENTS[a](ctx)
        for it in items:
            rpc(client, a, "tools/call", {"name": f"propose_{it['type']}",
                                          "arguments": {"run_id": rid, "payload": it["payload"]}}, tok)
        rpc(client, a, "tools/call", {"name": "finish_run", "arguments": {"run_id": rid}}, tok)
        hook(client, {"run_id": rid, "status": "completed"}, delivery=rid)
    with session_scope() as s:
        runs_ = s.scalars(select(AgentRun).where(AgentRun.backend == "creao")).all()
        assert {x.agent for x in runs_} == {x["input"]["agent"] for x in creao}
        assert all(j.status == "done" for j in s.scalars(select(Job).where(Job.run_id.in_([x["input"]["run_id"] for x in creao]))))
```

(For `qa_reviewer`, the real Creao agent would call `rules_engine`. The stub `recompute` keeps the test about plumbing, not rules.)

- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Write `creao_contract.md`, `charters.py` and `docs/creao-integration.md`.**
- [ ] **Step 4: Run `uv run pytest` and confirm the whole suite passes.**
- [ ] **Step 5: Print and read a charter** — `uv run python -m ellis.agents.charters case_manager`. It should read as a complete, self-contained Creao system prompt.
- [ ] **Step 6: Commit** — `git commit -m "docs(creao): charters, integration runbook, simulated end-to-end Creao run"`

---

## Deferred (deliberately not in this plan)

- **Polling Creao for run status** (spec "Polling is the fallback"). The expiry sweep covers lost webhooks. Add `GET /v1/runs/{id}` polling when the real API is confirmed and webhooks prove lossy.
- **A local tool-use backend** (`AnthropicBackend` calling `registry.call` through Claude tool use) for credit-free charter tuning. The registry is already framework-agnostic, so this is one backend class when needed.
- **A clinic-wide inbox scoped to one case.** `email_search` returns whatever the external server returns, so enable it only for clinics that accept this. Every call is in the work log.
- **A transcript PDF.** The clinic already sees transcripts in the Transcript tab, which respects retention.
