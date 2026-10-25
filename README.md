# Ellis

Ellis is a agentic immigration assistant built for small legal clinics to help individuals navigate the U.S naturalization process. 

## Inspiration

The U.S naturalization process is incredibly difficult to navigate, the bureaucracy behind the N-400 form is incredibly confusing, the process requires you to remember obscure details from years ago, and for those whose first language isn't English naturalization is a nightmare. Additionally, this story is personal to us as a team, as several of our parents have gone/are currently going through this arduous process, and like most Americans-to-be they found it incredibly frustrating and had to consult legal clinics for advice. Unfortunately, smaller legal clinics who typically help those within their communities are become more overwhelmed by the day, and either have to make people wait incredibly long times for appointments, or have to turn them away all together. 

## What it does

An applicant talks through their case in a language of their choice at their own pace instead of filling out forms, and Cartesia's voice agent carries the entire conversation, with turn detection for natural back-and-forth and word-level timestamps so interrupting Ellis mid-sentence4 cuts it off where you started talking. Every fact gets checked as it's said. For example, a hedged answer triggers a read-back before it's trusted, a stated fact that needs a document opens a gap on the case, and anything touching a serious issue (arrest, removal, fraud) halts the session immediately for attorney review, meaning no AI judgment call. Behind that single conversation, four highly specialized and trained Creao legal agents work the case like a real legal team. A case manager coordinates the file, a document paralegal checks uploads against stated facts, a docketing clerk tracks deadlines, and a QA reviewer does a final pass. Each proposes changes through a typed, authority-checked API rather than writing to the case directly. The clinic's attorneys review everything flagged before the applicant signs off. Ellis never tells someone they qualify, and it never files anything itself, rather it just guides the person through the process and does the unglamorous labor for them a legal clinic can use. 

## How we built it

A React.js app hosted on Vercel has the Cartesia voice agent as the main interface the user interacts with. Cartesia's Ink-2 does  streaming speech-to-text over a websocket, with turn detection (turn.start/turn.end) driving barge-in and end-of-turn — no push-to-talk button needed to know when someone's finished speaking. Replies go out through Sonic streaming text-to-speech with word-level timestamps (add_timestamps: true), which is what lets an applicant interrupt mid-sentence and have playback cut exactly at the word they started talking over, not the next audio chunk boundary. A tap starts a turn by streaming mic PCM16 and sending talk-down; release (or Ink's own turn.end) closes it. Three categories of line are locked and never interruptible by design: the consent disclosure, the stop-now safety script, and secure-entry prompts. Ellis talks in all 44 languages Sonic 3.6 speaks, in the accent the applicant picks (for example es-MX, fr-CA or pt-BR), and each applicant can choose Ellis's voice; for languages Ink-2 doesn't hear (it covers English, Spanish, French, Hindi and Japanese), speech-to-text switches to ink-whisper. The same Claude-driven liaison is also wired up as a Cartesia Line Agent (line_app.py, metadata.case_id), callable with ELLIS_LINE_BRAIN=llm for an LlmAgent behind HTTP tools. 

On the backend, a team of four specialized Creao agents runs to actually fill out the naturalization forms, create case books, and give communication to Cartesia on what needs to be followed up on or asked. The case manager, document paralegal, docketing clerk, and QA reviewer are each their own Creao app with their own API key and app ID, with custom playbooks adapted from Harvey's Legal Agent Benchmark(LAB) task patterns. We chose LAB to give context to our Creao agents because the benchmark's tasks are written by actual lawyers, and we wanted to ensure our agents had the context to actually assist with naturalization. From there, we further fine-tuned each agent into a specialized legal employee by giving a prompt based on the relevant tasks from the benchmark, as well as specific tools we created in the backend that each agent has access to in order to not only do the naturalization work, but also to communicate with Cartesia. In this case, some of the tools included were a fact checker that would check what the user was saying compared to what their documents said, document parsers, as well as communication tools to ensure Cartesia knew what to ask and when to ask. 

Our backend calls each agent directly (POST .../apps/<app_id>/runs, polling GET .../runs/<id> until it leaves pending/running), then translates whatever native shape that agent's engine returns — a fenced JSON block in chat text for some, a downloadable artifact file for others — into one typed proposal envelope. Authority is enforced in our own code, not just assumed from the prompt: a dict keyed by agent name defines exactly which item types and kinds each one may propose, and anything outside that gets rejected and logged, not silently dropped. Agents propose; they never write to the case directly. We also wired a rough Gmail integration ourselves (not through Creao's own connector) — a hedged travel date triggers a consent question, and only on a yes does it search for a confirming email, surfacing whatever it finds as a candidate for voice read-back, never as a written fact.

Everything else is a straightforward FastAPI + React stack, Python 3.12 with uv, Postgres in production, React + Vite + TypeScript on the frontend. The case itself is an append-only event log, not a mutable row — corrections supersede, they never overwrite. Dates, deadlines, and fee math run through a pure rules engine with a versioned config; no model ever computes a date. Document extraction runs in a sandboxed subprocess with no DB credentials. And the one rule that holds everywhere, for every agent and every tool: nothing an AI finds — a document match, a search result — becomes a confirmed fact without the applicant hearing it read back and saying yes out loud. That's enforced by the schema itself, not left to a prompt instruction.

Agents (IDs and links): Case manager: f34f8806-2859-47bb-bd13-2e2745df9da6, Document paralegal: 72a8da32-5d0b-43bb-8444-6bac87d7aa28, Docketing clerk: eac1bd98-c08a-441e-b1bd-97e29c33f0cb, QA reviewer: 95f10378-bceb-4b2d-9376-e75f5cca3906. Install links are in the Try it out section; run share links: Case manager run: https://agent.creao.ai/install/f34f8806-2859-47bb-bd13-2e2745df9da6?version=c7684901-ea53-4e5e-815d-b36fd6aae9d7, Document paralegal run: https://agent.creao.ai/install/72a8da32-5d0b-43bb-8444-6bac87d7aa28?version=c7664e28-c9d8-426a-bbd4-448e2f1ae7df, Docketing clerk run: https://agent.creao.ai/install/eac1bd98-c08a-441e-b1bd-97e29c33f0cb?version=b766e0c9-4cd9-4d0a-99bb-4c51ced3427a, QA reviewer run: https://agent.creao.ai/install/95f10378-bceb-4b2d-9376-e75f5cca3906?version=6832ec16-ed7e-4dc4-82fa-f675cffd200d

## Why We Built It This Way

We wanted the entire experience to feel seamless for those whose first language wasn't English, which is why we chose Cartesia since it can support several languages and locales, and why we are happy to show in the live demo on Sunday that our application supports several languages. Additionally, considering many are unsure about information they give during naturalization since many of it is obscure or from years ago, we also wanted voice agent software that can detect uncertainty and follow up on it. For the backend, we used a team of Creao legal agents because we wanted a way to easily deploy specialized agents that can not only do the work for naturalization, but also communicate with Cartesia to ensure its asking the right questions. The entire project would break without Creao because otherwise we wouldn't have been able to focus on making each agent incredibly specialized, the no code prompt and deploy via an API made the entire process very easy so we could instead focus on making each agent as specialized as possible. 


## Challenges we ran into

*Initial iterations of Cartesia voice agent conversation felt like the agent was reading off a checklist instead of having real conversation
*Cartesia's voice agent was too sensitive to background noise, so we created a toggle to talk feature, implemented a decible based system to find out who the main speaker was, 
*The web application had several bugs causing Spanish to be hardcoded into text displayed on the website
*Creao's MCP connectors intially refused to connect cleanly, and required outside API keys that wouldn't register
*Creao's playbook and agents would sometimes not save causing us to restart progress

## Accomplishments that we're proud of

*The Creao agents are incredibly good at the tasks they do because of the legal agentic benchmark tasks used to create them and work incredibly well together
*The Creao legal agentic team backend is able to seamlessly communicate with the Cartesia voice agent to guide it on questions to ask
*The Cartesia voice agent flows seamlessly within conversation and feels like you're talking to a real person
*The Cartesia voice agent logic we built deals with background noise very effectively and can spot uncertainty in wordage easily

## What we learned

*A third-party agent platform having a tool connected doesn't mean the agent's own instructions were ever told to use it, we confirmed this when one agent reported its Gmail connector was active and still never used it, because nothing in its prompt said when to
*Altough it didn't relate to the sponsor track products themselves, we learned that developing on multiple seperate tracks and merging them later ended up being the most effective strategy for us

## What's next

Moving into other parts of the immigration process such as Visas or aslyum, as well as reaching out the small legal clinics to test our product more and see how it works in real work enviornments. 

## Try it out

## Technical documentation

Ellis is a voice-first naturalization (N-400) preparation app for small immigration law clinics and their clients. An applicant does intake by speaking in their own language — any of the 44 that Cartesia's Sonic speaks, in their own accent — at their own pace, on their phone. AI staff agents build the case file. The clinic's attorneys and accredited representatives review flagged items and approve. The applicant confirms every fact and signs. **Ellis never files and never gives legal advice.**

Two sides:
- **Client (applicant):** chat, form, interview prep, reminders, review and sign-off.
- **Clinic workspace:** case list, case detail (facts, documents, review, activity, memos, transcript, packet).

### Quick start

Requirements: Python 3.12+, Node 20+, Postgres 16 / Supabase (or SQLite for zero-setup dev).

All Python runs from a virtualenv at the repo root, `.venv`. Nothing is installed globally.

```bash
cp backend/.env.example backend/.env   # fill in keys (see table below)
./scripts/dev.sh                       # creates .venv if missing; seeds demo data; API :8000, web :5173
```

`scripts/dev.sh` creates `.venv` and installs the backend into it on first run. To set it up by hand
(or after changing `backend/pyproject.toml`):

```bash
python3 -m venv .venv                  # from the repo root, once
source .venv/bin/activate              # every new terminal
pip install -e "backend[llm,dev]"      # add ,line for the Cartesia Line agent
```

Run the API alone, from the venv:

```bash
source .venv/bin/activate && cd backend
uvicorn ellis.api.app:app --reload --port 8000
```

Open http://localhost:5173:

- **Clinic workspace:** `/clinic` — sign in as `dana@valle.demo` (reviewer), `sam@valle.demo` (intake), or `admin@valle.demo`. Password `ellis-demo`.
- **Applicant links:** `/a/demo-maria`, `/a/demo-jorge`, `/a/demo-ana`, `/a/demo-rosa`. A link signs the applicant in and lands on the chat.

All data is synthetic. The demo flows are written for Friday, Oct 23, 2026, so `ELLIS_TODAY=2026-10-23` pins the date (`scripts/dev.sh` sets this automatically).

#### Environment variables (`backend/.env`, gitignored)

| Variable | Purpose |
|---|---|
| `CARTESIA_API_KEY` | Streaming STT (Ink-2 with turn detection, ink-whisper for other languages) and Sonic TTS with word timestamps |
| `CARTESIA_VOICE_ID` | Spanish (es-MX) Sonic voice — auto-discovered when empty |
| `CARTESIA_TTS_MODEL` | Default: `sonic-3.6` (44 languages; takes the accent as `locale`). Older models get only the base language |
| `CARTESIA_STT_MODEL` | Default: `ink-2` (turn-detection model for en, es, fr, hi, ja; other languages always use `ink-whisper`) |
| `ANTHROPIC_API_KEY` | Required for the applicant chat (Claude drives it); also enables staff agents and vision extraction |
| `DATABASE_URL` | Postgres / Supabase session pooler recommended; defaults to SQLite |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_BUCKET` | Private Supabase Storage bucket for case files; unset = local disk |
| `ELLIS_TOOL_SECRET`, `ELLIS_SESSION_SECRET`, `VAULT_KEY` | Liaison tool auth, cookie signing, AES-GCM vault |
| `ELLIS_AGENT_BACKEND` | `skeleton` (no keys needed), `anthropic`, or `creao` |
| `CREAO_BASE_URL`, `<AGENT>_API_KEY`, `<AGENT>_APP_ID` | Creao dispatch: one key + app id per agent (`CASE_MANAGER`, `DOC_PARALEGAL`, `DOCKETING_CLERK`, `QA_REVIEWER`); runs are polled to completion |
| `CREAO_WEBHOOK_SECRET` | Only for the optional `POST /webhooks/creao` route, which refuses every request without it |
| `ELLIS_PUBLIC_BASE_URL` | Base URL for generated links (default: `http://localhost:5173`) |
| `ELLIS_TODAY` | Pin the demo date (empty = real date) |

Without Cartesia keys, the voice session falls back to text mode: lines appear as captions only.

### Tests and e2e

```bash
# Backend (from the repo-root venv)
source .venv/bin/activate
cd backend && pytest

# Frontend build (must pass before committing)
cd frontend && npm run build

# E2e happy path (requires app running via ./scripts/dev.sh)
cd frontend
npx playwright install chromium
npm run e2e          # clinic + applicant sign-off
npm run screenshots  # 390px + 1280px shots → frontend/e2e-shots/ (gitignored)

# Evals (Spanish flow conversations, pinned date)
source .venv/bin/activate && cd backend
ELLIS_TODAY=2026-10-23 python -m evals.flows all -v
```

### Cartesia features used

- **Every Sonic language and accent** — `backend/config/languages.yaml` lists Sonic 3.6's 44 languages and 57 locales (e.g. `es-MX`, `fr-CA`, `pt-BR`, `en-IN`). The applicant picks a language and accent, and can choose Ellis's voice from Cartesia's voices for that accent (each one says Ellis's greeting first). Sonic gets the accent as `locale`.
- **Ink-2 STT** — streaming speech-to-text over WebSocket (`wss://api.cartesia.ai/stt/turns/websocket`) for English, Spanish, French, Hindi and Japanese. Turn detection (`turn.start`, `turn.end`) drives barge-in and end-of-turn without a button.
- **ink-whisper STT** — every other language (`wss://api.cartesia.ai/stt/websocket?language=…`). No turn detection: releasing the talk button sends `finalize`, and tap-to-talk ends on a second tap. Odia has no speech-to-text; Odia speakers type.
- **Sonic TTS** — streaming text-to-speech with word timestamps (`add_timestamps: true`). Word timestamps let barge-in cut audio at the exact word being spoken, not at a chunk boundary.
- **Tap-to-talk with interruption** — pointer-down sends talk-down and starts streaming mic PCM16; pointer-up (or a `turn.end` from Ink) ends the turn. Tapping while Ellis is speaking interrupts playback at the current word.
- **Locked lines** — consent disclosure, stop-now script, and secure-entry prompts are never cut off; the applicant's turn is held until the locked line finishes speaking.
- **Cartesia Line agent** (`backend/ellis/voice/line_app.py`) — the same LLM liaison as a Line `Agent`, callable with `metadata.case_id`. Start calls with `ELLIS_LINE_BRAIN=llm` to use a Claude `LlmAgent` with HTTP tools behind the keyword guard.

### Agent team

Four AI staff agents run after each fact change (debounced, `SKIP LOCKED`, with retry and `run_id` dedupe):

| Agent | Label in UI | What it owns |
|---|---|---|
| Case manager | Case coordinator | Proposes eligibility basis, detects conflicts across facts, flags stop-now events |
| Document paralegal | Document checker | Reads uploaded documents (vision extraction in sandbox subprocess), matches extracted fields to case facts, identifies gaps |
| Docketing clerk | Deadline tracker | Computes filing windows, presence days, and upcoming deadlines; proposes a briefing queue |
| QA reviewer | Quality check | Writes a structured QA memo, flags unresolved issues and ambiguous facts, marks the case ready for reviewer sign-off |

Each agent is a prompt file (`backend/prompts/<agent>.md`) plus a typed proposal envelope (`backend/ellis/agents/proposals.py`). The Case API enforces authority limits in code — agents propose; the API validates and writes with provenance.

**Skeleton agents** (`backend/ellis/agents/skeleton.py`) are deterministic implementations of the same contract and need no API keys. To use Creao: create the four saved agents on Creao, set `ELLIS_AGENT_BACKEND=creao`, `CREAO_BASE_URL`, and each agent's `<AGENT>_API_KEY` / `<AGENT>_APP_ID`. Ellis starts each run and polls it to completion; no webhook is needed.

Playbooks were adapted from Harvey's Legal Agent Benchmark task patterns. We do not report LAB scores; we evaluate on our own synthetic N-400 cases with an all-pass grading rubric (`backend/evals/`).

### Responsibility

- **AI disclosure and consent first.** The liaison speaks a disclosure before any intake: Ellis is not a lawyer, the clinic reviews the case, conversation text is saved, audio is not. The applicant says "I agree" before any fact is recorded. Declining consent stops the session.
- **No legal advice.** Ellis never says "you qualify" or "you can file." Filing-window estimates from the rules engine are labeled "earliest filing date — your clinic will confirm."
- **Nothing filed without attorney approval.** "Mark ready" is a reviewer action that gates the applicant sign-off screen. The applicant signs; the packet goes to the clinic. Ellis never submits to USCIS.
- **Audio not stored.** Only conversation text (`Utterance` rows) is stored. Audio streams through and is not persisted.
- **Synthetic data only in the demo.** The demo clinic `Valle Legal` uses seeded synthetic cases (marked "Datos de demostración"). No real client data is in this repository.
- **Escalations go to the attorney.** Stop-now events block the case immediately and require a reviewer decision before intake can continue.

### Known limitations

#### Mocked or demo-only
- `ELLIS_AGENT_BACKEND=skeleton` (the default) uses deterministic agents — no Claude calls, no Creao. Set `ELLIS_AGENT_BACKEND=anthropic` or `creao` to use real agents.
- Vision document extraction requires `ANTHROPIC_API_KEY`. Without it, uploads are accepted but not extracted.
- The Cartesia Line deployment (`line_app.py`) is wired but not deployed in the demo.
- Applicant `/review` sign-off: the "Listen to this section" button uses browser `speechSynthesis`, not Cartesia.

#### Needs USCIS expert check before any real use

| Item | File | Line |
|---|---|---|
| N-400 edition and background question text | `backend/config/background_questions.yaml` | 1 |
| Trip-day convention (calendar difference vs. departure/return day counts) | `backend/config/rule_config/2026.10-a.yaml` | 3 |
| Fee waiver criteria and poverty table | `backend/config/fees.yaml` | 7–9 |
| Pending fee rule (effective-date treatment) | `backend/config/fees.yaml` | 20 |
| Preparer/interpreter section of N-400 | `backend/config/n400_fields.yaml` | 36 |
| Civics test "12 of 20" passing threshold | `frontend/src/Interview.tsx` | 123 |
| All fees and form editions shown to applicants | `backend/prompts/guest_faq.md` | — |

#### Skipped in this build
- Applicant `/review` page has no Playwright coverage yet.
- Full i18n pass on clinic, sign-in, sign-up: English only.
- Phase 4 component refactor and spacing token system: not done.
- Spanish strings added in this session are machine-translated drafts marked for human review.
- Languages other than English and Spanish: Ellis talks in them, but screens and Ellis's server text stay in English, and field labels come from `fields.yaml` in English. Their fixed legal lines (`backend/ellis/voice/scripts_<lang>.yaml`) and keyword lists (`backend/config/keywords_i18n.yaml`) are machine-translated drafts (`reviewed: false`); the chat shows the English original under each fixed line until reviewed. The scripted Line brain (`ELLIS_LINE_BRAIN=scripted`) parses English and Spanish only.

### Architecture

```
Browser (applicant /a/:token, clinic /clinic)         React + Vite (frontend/)
   │  WS /api/a/voice  (mic PCM16 16 kHz ⇄ Sonic PCM 24 kHz, captions, barge-in)
   │  REST /api/a/*, /api/clinic/*
   ▼
Case API — FastAPI (backend/ellis)
   ├─ voice/        liaison turn engine, Cartesia gateway, Line agent, scripts_<lang>.yaml
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
