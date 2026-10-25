# Ellis

Ellis is people-first software for small legal clinics that prepare naturalization (Form N-400) cases. Each
applicant does intake by voice, in Spanish, at their own pace. AI staff agents build the case file in the
background. The clinic's attorneys and accredited representatives review flagged items and approve the case.
The applicant confirms every fact and signs. **Ellis never files and never gives legal advice.**

This repo holds the **Phase 1 MVP** (stages 0–4: consent, eligibility screen, intake, evidence, review gate and
sign-off), built from [`docs/oneshot.md`](docs/oneshot.md). Phase 2 (study and mock interview) and stages 5, 6,
9 and 10 appear only on the roadmap card.

## Quick start

Requirements: Python 3.12+, Node 20+, and optionally Postgres (or a Supabase project). All Python runs from a
virtualenv at the repo root, `.venv/` (gitignored).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "backend[llm,dev]"          # add ,line for the Cartesia Line app
cp backend/.env.example backend/.env    # then fill in keys (see below)
./scripts/dev.sh                        # seeds demo data, runs the API on :8000 and the web app on :5173
```

Then open http://localhost:5173:

- **Clinic workspace:** `/clinic`. Sign in as `dana@valle.demo` (reviewer), `sam@valle.demo` (intake) or
  `admin@valle.demo`. The password is `ellis-demo`.
- **Applicant links (Spanish):** `/a/demo-maria`, `/a/demo-jorge`, `/a/demo-ana`, `/a/demo-rosa`. A link signs the
  applicant in and lands on the chat (`/`). The sidebar pages are `/form`, `/interview`, `/reminders` and `/advanced`.
  Sign-off is at `/review`. Without a session, `/` goes to `/signin`, where the link or its code can be pasted.

All data is synthetic, and the UI labels it "Datos de demostración". The flows are written for Friday
Oct 23, 2026, so `ELLIS_TODAY` pins the date (`scripts/dev.sh` sets it).

### Keys and configuration (`backend/.env`, gitignored)

| Variable | Purpose |
|---|---|
| `CARTESIA_API_KEY` | Voice: Ink-2 streaming STT with turn detection, and Sonic TTS with word timestamps. |
| `CARTESIA_VOICE_ID` | Spanish (es-MX) Sonic voice. When empty, one is auto-discovered from `/voices`. |
| `ANTHROPIC_API_KEY` | Required for the applicant chat: Claude drives the whole conversation (`ELLIS_CONVERSATION_MODEL`). Also enables the Claude staff agents (`ELLIS_AGENT_BACKEND=anthropic`) and vision extraction for real photos. |
| `DATABASE_URL` | Postgres is recommended (`postgresql+psycopg://…`; NOTIFY trigger and `SKIP LOCKED`). Defaults to SQLite. |
| `ELLIS_TOOL_SECRET`, `ELLIS_SESSION_SECRET`, `VAULT_KEY` | Liaison tool auth, cookie signing, and AES-GCM for sensitive values. |
| `ELLIS_AGENT_BACKEND` | `skeleton` (deterministic, no model), `anthropic`, or `creao`. |
| `CREAO_API_KEY`, `CREAO_AGENT_<AGENT>`, `ELLIS_PUBLIC_API_URL` | Creao dispatch. Results arrive at `POST /webhooks/creao`. |

Without a reachable Cartesia, the voice session falls back to **text mode**. Lines appear as captions and are
spoken by the browser's es-MX voice. The applicant can type or use browser speech recognition, and barge-in
still works.

## Architecture

```
Browser (applicant /a/:token, clinic /clinic)          React + Vite (frontend/)
   │  WS /api/a/voice  (mic PCM16 16 kHz ⇄ Sonic PCM 24 kHz, captions, barge-in)
   │  WS /api/a/stream, /api/clinic/stream (live updates)        REST /api/a/*, /api/clinic/*
   ▼
Case API — FastAPI (backend/ellis)  ← the only writer to the database; every write appends an event
   ├─ voice/        liaison turn engine (Spanish), Cartesia gateway, Line agent (line_app.py), scripts_es.yaml
   ├─ services/     record_fact, read-back/correction, conflict rule, flags (4 layers), stop-now, vault,
   │                gate, state machine, briefing, documents, sign-off, views
   ├─ rules/        pure rules engine (dates, presence, exemptions, fees) — 100% branch coverage
   ├─ agents/       runner (debounce, SKIP LOCKED, retries, run_id dedupe) + case manager, doc paralegal,
   │                docketing clerk, QA reviewer; backends: skeleton | anthropic | creao
   ├─ extraction/   sandboxed worker subprocess (no DB credentials), per-type Pydantic schemas
   └─ packet/       N-400 draft, online copy sheet, evidence index, fee sheet, checklist, I-912, reviewer summary
Postgres (or SQLite): clinic, staff_user, cases, case_link, session, utterance, fact, vault_value, event,
document, extraction, briefing, task, flag, review_item, derived, deadline, memo, gap, agent_run, jobs, signoff, packet
```

Key invariants:

- The liaison never waits on staff agents.
- Models never compute dates; the rules engine does, with a `rule_config_version`.
- Agents propose and the Case API validates and writes with provenance. Corrections supersede; they never overwrite.
- Sensitive numbers are typed, never spoken, and models only see tokens like `[A_NUMBER]`.
- Stop-now disclosures store only the category and a timestamp. The words are never written anywhere.

### Voice

- **In-house gateway** (`ellis/api/routes/voice.py`, `ellis/voice/cartesia.py`) runs the web demo:
  - It streams mic audio to `wss://api.cartesia.ai/stt/turns/websocket` (Ink-2). `turn.start` triggers barge-in and `turn.end` carries the final transcript.
  - It speaks through the Sonic WebSocket with `add_timestamps`.
  - A barge-in maps to the word being spoken, using Sonic's word timestamps and the browser's playback clock.
  - Locked lines (disclosure, stop script, secure entry) are never cut off; the applicant's turn is held until the line ends.
- **Cartesia Line deployment** (`ellis/voice/line_app.py`) is the same liaison as a Line `Agent`:
  - Start calls with `metadata.case_id`.
  - `ELLIS_LINE_BRAIN=llm` uses a Claude `LlmAgent` with HTTP tools, behind the layer-4 keyword guard.
  - Run it with `python -m ellis.voice.line_app` (venv active; needs the `line` extra).

### Staff agents and Creao

Each agent is a prompt file (`backend/prompts/<agent>.md`) plus a typed proposal envelope
(`ellis/agents/proposals.py`). The authority limits in that module are enforced in code.

- **Skeleton agents** (`ellis/agents/skeleton.py`) are deterministic implementations of the same contract. They need no keys and use no credits.
- **To swap in Creao:** create the four saved agents, set `ELLIS_AGENT_BACKEND=creao` and the `CREAO_*` variables, and point their webhook at `/webhooks/creao`.

## Tests and evals

```bash
source .venv/bin/activate && cd backend
pytest                      # rules T1–T18 + acceptance AT1–AT20 + flows F1–F4 (57 tests)
TEST_DATABASE_URL=postgresql+psycopg://ellis:ellis@localhost/ellis_test pytest   # on Postgres
ELLIS_TODAY=2026-10-23 python -m evals.flows all -v   # print the full Spanish conversations
```

The flow evals drive the real liaison, Case API, agent runner and packet builder with a simulated applicant.
They cover planted hedges, barge-in corrections, an arrest disclosure, document uploads, reviewer decisions and
sign-off. They report planted-issue recall (currently 100%) and false alarms (currently none).

`frontend/e2e/happy-path.cjs` is the Playwright happy path through the clinic UI, review queue and applicant
sign-off.

## NEEDS EXPERT CHECK / open questions

Defaults follow the spec's open-questions table, and `TODO(open-question-N)` marks where each answer plugs in:

- **N-400 edition (1):** background question text is a paraphrase marked `verified: false` and must be copied from the verified edition.
- **Trip-day convention (2):** calendar difference.
- **Preparer section (8):** left blank.
- **Waiver criteria and poverty table (9):** pinned values, not yet verified.
- **Pending fee rule (10):** shown as a watch notice only.

Spanish copy is a draft and needs native review. Re-verify all rules and fees on uscis.gov before any real use.
