# Ellis — CLAUDE.md

## What Ellis is

Ellis is a voice-first naturalization (N-400) preparation app for small immigration law clinics. An applicant
does intake by talking in their own language (any of the 44 that Cartesia's Sonic speaks). AI staff agents
build the case file. The clinic's attorneys and accredited representatives review flagged items and approve.
The applicant confirms every fact and signs.

**Ellis never files and never gives legal advice.**

Two sides:
- **Client (applicant):** `/`, `/form`, `/interview`, `/reminders`, `/profile`, `/review`
- **Reviewer (clinic staff):** `/clinic`, `/clinic/cases/:id`, `/clinic/review`, `/clinic/settings`

## Running the app

```bash
cp backend/.env.example backend/.env   # fill in keys
./scripts/dev.sh                       # creates .venv if missing; seeds demo data; API :8000, web :5173
```

Demo logins:
- Clinic staff: `dana@valle.demo` (reviewer), `sam@valle.demo` (intake), `admin@valle.demo` — password `ellis-demo`
- Applicant links: `/a/demo-maria`, `/a/demo-jorge`, `/a/demo-ana`, `/a/demo-rosa`

## Backend

All Python runs from the repo-root virtualenv `.venv` — never uv, never a global install.
`scripts/dev.sh` creates it on first run; by hand:

```bash
python3 -m venv .venv                  # repo root, once (Python 3.12+)
source .venv/bin/activate              # every new terminal
pip install -e "backend[llm,dev]"      # add ,line for the Cartesia Line agent
```

With the venv active:

```bash
cd backend
uvicorn ellis.api.app:app --reload --port 8000   # development server
pytest                                           # rules + acceptance + portal + agent
ELLIS_TODAY=2026-10-23 python -m evals.flows all -v   # Spanish flow evals
```

`backend/uv.lock` is stale and unused; `pyproject.toml` is the source of truth.

## Frontend

```bash
cd frontend
npm install
npm run dev          # Vite dev server :5173
npm run build        # tsc + Vite build (must pass before committing)
```

## Tests and e2e

```bash
# Backend (venv active)
source .venv/bin/activate && cd backend && pytest

# Frontend e2e (requires app running via ./scripts/dev.sh)
cd frontend
npx playwright install chromium
npm run e2e            # Playwright happy path (clinic + applicant sign-off)
npm run screenshots    # 390px + 1280px shots → frontend/e2e-shots/ (gitignored)
```

## Main directories

```
backend/
  ellis/
    api/routes/      FastAPI routes (applicant a.*, clinic clinic.*, guest, voice WS)
    services/        Domain logic: case_service.py, documents.py, guest.py, views.py,
                     activity.py, catalog.py, accounts.py, storage.py
    rules/           Pure rules engine (dates, presence, fees)
    voice/           LlmLiaison, Cartesia gateway, scripts_<lang>.yaml
    agents/          Staff agents (case_manager, doc_paralegal, docketing_clerk, qa_reviewer)
    extraction/      Sandboxed document extraction worker
  config/
    fields.yaml      The one field label map (label_en, label_es)
    n400_fields.yaml N-400 part structure
  prompts/           guest_faq.md, guest_guide.md, liaison.md, agent prompts
  tests/             test_acceptance.py, test_portal.py, test_rules.py, test_agent.py
frontend/
  src/
    Chat.tsx         Signed-in applicant chat (voice + typing)
    GuestChat.tsx    Logged-out guide
    applicant/       Guide.tsx, voice.ts, i18n.ts, ApplicantApp.tsx, …
    clinic/          CaseDetail.tsx, CaseList.tsx, ReviewQueue.tsx, ClinicApp.tsx
    styles.css       Design tokens + most rules (no Tailwind, no CSS modules)
    app.css          Clinic tables, demo tag, late additions
  e2e/               Playwright specs (happy-path.cjs, screenshots.spec.ts)
docs/
  ux-overhaul-plan.md  Phase 0 map, decisions, phase checklists — read this before touching UX
```

## Standing rules (apply to every change)

1. **Never invent legal rules, fees, numbers, timelines, or USCIS facts.** Use
   `[VERIFY against current USCIS source]` placeholders. This applies to copy, comments, and code.

2. **Never claim privacy or storage behavior the code does not have.** What the code does:
   conversation text is saved as `Utterance` rows; audio is not stored; Ellis does not file.
   Do not add privacy claims beyond that.

3. **Ellis never gives legal advice or eligibility judgments.** Any outcome statement must end with
   "Your clinic will review this" or equivalent.

4. **Languages come from `backend/config/languages.yaml` only.** It lists every language and accent Cartesia's
   Sonic speaks; both sides' pickers read it through `GET /api/languages`. Never add a second language list.
   Ellis talks in the case's language (`case_language()`); Ellis's own screen and server text exists in English
   and Spanish only (`case_lang()`: every other language reads English). The fixed legal lines
   (`voice/scripts_<lang>.yaml`) and keyword lists (`config/keywords_i18n.yaml`) for languages other than English
   and Spanish are machine-translated drafts: never mark one `reviewed: true` without a native speaker's review.

5. **Field labels come from `backend/config/fields.yaml` only** — `catalog.label_en` / `label_es` through
   the API. Never add a second frontend label map. A key missing from `fields.yaml` title-cases.

6. **Keep demo-only controls behind demo mode.** `d.clinic.is_demo` is the gate. Never show demo
   controls to real-clinic users.

7. **Keep existing tests passing.** Add tests for new backend behavior. Run `pytest` (from the `.venv`) before
   committing backend changes; run `npm run build` before committing frontend changes.

8. **Small commits, one per feature item, clear messages. Never push.**
