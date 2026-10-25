# Ellis

Ellis is a voice-first naturalization (N-400) preparation app for small immigration law clinics and their clients. An applicant does intake by speaking in Spanish (or English) — at their own pace, on their phone. AI staff agents build the case file. The clinic's attorneys and accredited representatives review flagged items and approve. The applicant confirms every fact and signs. **Ellis never files and never gives legal advice.**

Two sides:
- **Client (applicant):** chat, form, interview prep, reminders, review and sign-off.
- **Clinic workspace:** case list, case detail (facts, documents, review, activity, memos, transcript, packet).

## Quick start

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 20+, Postgres 16 (or SQLite for zero-setup dev).

```bash
cp backend/.env.example backend/.env   # fill in keys (see table below)
./scripts/dev.sh                       # seeds demo data; API :8000, web :5173
```

Open http://localhost:5173:

- **Clinic workspace:** `/clinic` — sign in as `dana@valle.demo` (reviewer), `sam@valle.demo` (intake), or `admin@valle.demo`. Password `ellis-demo`.
- **Applicant links:** `/a/demo-maria`, `/a/demo-jorge`, `/a/demo-ana`, `/a/demo-rosa`. A link signs the applicant in and lands on the chat.

All data is synthetic. The demo flows are written for Friday, Oct 23, 2026, so `ELLIS_TODAY=2026-10-23` pins the date (`scripts/dev.sh` sets this automatically).

### Environment variables (`backend/.env`, gitignored)

| Variable | Purpose |
|---|---|
| `CARTESIA_API_KEY` | Ink-2 streaming STT with turn detection, and Sonic TTS with word timestamps |
| `CARTESIA_VOICE_ID` | Spanish (es-MX) Sonic voice — auto-discovered when empty |
| `CARTESIA_TTS_MODEL` | Default: `sonic-3` |
| `CARTESIA_STT_MODEL` | Default: `ink-2` |
| `ANTHROPIC_API_KEY` | Required for the applicant chat (Claude drives it); also enables staff agents and vision extraction |
| `DATABASE_URL` | Postgres recommended; defaults to SQLite |
| `ELLIS_TOOL_SECRET`, `ELLIS_SESSION_SECRET`, `VAULT_KEY` | Liaison tool auth, cookie signing, AES-GCM vault |
| `ELLIS_AGENT_BACKEND` | `skeleton` (no keys needed), `anthropic`, or `creao` |
| `CREAO_API_KEY`, `CREAO_BASE_URL`, `CREAO_WEBHOOK_SECRET` | Creao dispatch; results arrive at `POST /webhooks/creao` |
| `ELLIS_PUBLIC_BASE_URL` | Base URL for generated links (default: `http://localhost:5173`) |
| `ELLIS_TODAY` | Pin the demo date (empty = real date) |

Without Cartesia keys, the voice session falls back to text mode: lines appear as captions and the browser's es-MX speech synthesis reads them aloud.

## Tests and e2e

```bash
# Backend (87 tests)
cd backend && uv run pytest

# Frontend build (must pass before committing)
cd frontend && npm run build

# E2e happy path (requires app running via ./scripts/dev.sh)
cd frontend
npx playwright install chromium
npm run e2e          # clinic + applicant sign-off
npm run screenshots  # 390px + 1280px shots → frontend/e2e-shots/ (gitignored)

# Evals (Spanish flow conversations, pinned date)
cd backend
ELLIS_TODAY=2026-10-23 uv run python -m evals.flows all -v
```

## Cartesia features used

- **Ink-2 STT** — streaming speech-to-text over WebSocket (`wss://api.cartesia.ai/stt/turns/websocket`). Turn detection (`turn.start`, `turn.end`) drives barge-in and end-of-turn without a button.
- **Sonic TTS** — streaming text-to-speech with word timestamps (`add_timestamps: true`). Word timestamps let barge-in cut audio at the exact word being spoken, not at a chunk boundary.
- **Tap-to-talk with interruption** — pointer-down sends talk-down and starts streaming mic PCM16; pointer-up (or a `turn.end` from Ink) ends the turn. Tapping while Ellis is speaking interrupts playback at the current word.
- **Locked lines** — consent disclosure, stop-now script, and secure-entry prompts are never cut off; the applicant's turn is held until the locked line finishes speaking.
- **Cartesia Line agent** (`backend/ellis/voice/line_app.py`) — the same LLM liaison as a Line `Agent`, callable with `metadata.case_id`. Start calls with `ELLIS_LINE_BRAIN=llm` to use a Claude `LlmAgent` with HTTP tools behind the keyword guard.

## Agent team

Four AI staff agents run after each fact change (debounced, `SKIP LOCKED`, with retry and `run_id` dedupe):

| Agent | Label in UI | What it owns |
|---|---|---|
| Case manager | Case coordinator | Proposes eligibility basis, detects conflicts across facts, flags stop-now events |
| Document paralegal | Document checker | Reads uploaded documents (vision extraction in sandbox subprocess), matches extracted fields to case facts, identifies gaps |
| Docketing clerk | Deadline tracker | Computes filing windows, presence days, and upcoming deadlines; proposes a briefing queue |
| QA reviewer | Quality check | Writes a structured QA memo, flags unresolved issues and ambiguous facts, marks the case ready for reviewer sign-off |

Each agent is a prompt file (`backend/prompts/<agent>.md`) plus a typed proposal envelope (`backend/ellis/agents/proposals.py`). The Case API enforces authority limits in code — agents propose; the API validates and writes with provenance.

**Skeleton agents** (`backend/ellis/agents/skeleton.py`) are deterministic implementations of the same contract and need no API keys. To use Creao: create the four saved agents on Creao, set `ELLIS_AGENT_BACKEND=creao` and the `CREAO_*` variables, and point their webhook at `POST /webhooks/creao`.

Playbooks were adapted from Harvey's Legal Agent Benchmark task patterns. We do not report LAB scores; we evaluate on our own synthetic N-400 cases with an all-pass grading rubric (`backend/evals/`).

## Responsibility

- **AI disclosure and consent first.** The liaison speaks a disclosure before any intake: Ellis is not a lawyer, the clinic reviews the case, conversation text is saved, audio is not. The applicant says "I agree" before any fact is recorded. Declining consent stops the session.
- **No legal advice.** Ellis never says "you qualify" or "you can file." Filing-window estimates from the rules engine are labeled "earliest filing date — your clinic will confirm."
- **Nothing filed without attorney approval.** "Mark ready" is a reviewer action that gates the applicant sign-off screen. The applicant signs; the packet goes to the clinic. Ellis never submits to USCIS.
- **Audio not stored.** Only conversation text (`Utterance` rows) is stored. Audio streams through and is not persisted.
- **Synthetic data only in the demo.** The demo clinic `Valle Legal` uses seeded synthetic cases (marked "Datos de demostración"). No real client data is in this repository.
- **Escalations go to the attorney.** Stop-now events block the case immediately and require a reviewer decision before intake can continue.

## Known limitations

### Mocked or demo-only
- `ELLIS_AGENT_BACKEND=skeleton` (the default) uses deterministic agents — no Claude calls, no Creao. Set `ELLIS_AGENT_BACKEND=anthropic` or `creao` to use real agents.
- Vision document extraction requires `ANTHROPIC_API_KEY`. Without it, uploads are accepted but not extracted.
- The Cartesia Line deployment (`line_app.py`) is wired but not deployed in the demo.
- Applicant `/review` sign-off: the "Listen to this section" button uses browser `speechSynthesis`, not Cartesia.

### Needs USCIS expert check before any real use

| Item | File | Line |
|---|---|---|
| N-400 edition and background question text | `backend/config/background_questions.yaml` | 1 |
| Trip-day convention (calendar difference vs. departure/return day counts) | `backend/config/rule_config/2026.10-a.yaml` | 3 |
| Fee waiver criteria and poverty table | `backend/config/fees.yaml` | 7–9 |
| Pending fee rule (effective-date treatment) | `backend/config/fees.yaml` | 20 |
| Preparer/interpreter section of N-400 | `backend/config/n400_fields.yaml` | 36 |
| Civics test "12 of 20" passing threshold | `frontend/src/Interview.tsx` | 123 |
| All fees and form editions shown to applicants | `backend/prompts/guest_faq.md` | — |

### Skipped in this build
- Applicant `/review` page has no Playwright coverage yet.
- Full i18n pass on clinic, sign-in, sign-up: English only.
- Phase 4 component refactor and spacing token system: not done.
- Spanish strings added in this session are machine-translated drafts marked for human review.

## Architecture

```
Browser (applicant /a/:token, clinic /clinic)         React + Vite (frontend/)
   │  WS /api/a/voice  (mic PCM16 16 kHz ⇄ Sonic PCM 24 kHz, captions, barge-in)
   │  REST /api/a/*, /api/clinic/*
   ▼
Case API — FastAPI (backend/ellis)
   ├─ voice/        liaison turn engine, Cartesia gateway, Line agent, scripts_es/en.yaml
   ├─ services/     record_fact, correction, conflict rule, flags, stop-now, vault,
   │                gate, state machine, briefing, documents, sign-off, views, activity
   ├─ rules/        pure rules engine (dates, presence, exemptions, fees) — 100% branch coverage
   ├─ agents/       runner (debounce, SKIP LOCKED, retries) + case manager, doc paralegal,
   │                docketing clerk, QA reviewer; backends: skeleton | anthropic | creao
   ├─ extraction/   sandboxed worker subprocess (no DB credentials), per-type Pydantic schemas
   └─ packet/       N-400 draft, evidence index, fee sheet, checklist, I-912, reviewer summary
Postgres (or SQLite): clinic, staff_user, cases, utterance, fact, event, document, extraction,
   briefing, task, flag, review_item, derived, deadline, memo, gap, agent_run, jobs, signoff, packet
```

Key invariants:
- The liaison never waits on staff agents.
- Models never compute dates; the rules engine does, with a versioned `rule_config`.
- Agents propose; the Case API validates and writes with provenance. Corrections supersede; they never overwrite.
- Sensitive numbers are typed, never spoken; models only see tokens like `[A_NUMBER]`.
- Stop-now disclosures store only the category and timestamp. The words are never written.
