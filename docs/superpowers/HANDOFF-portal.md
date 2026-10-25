# Handoff: Ellis portal (accounts + UI)

## Scope
Build a working application: the app logic and UI that let a guest, an applicant and a clinic use Ellis end to end. Out of scope here: agents, Cartesia/voice, Supabase (migration comes later and isn't a design input).

## Where the work lives
- **Worktree:** `/Users/aarushnarayanan/ellis/.claude/worktrees/portal`
- **Branch:** `portal`, cut from `cartesia-fix` at 8717787.
- **Spec:** `docs/superpowers/specs/2026-10-24-portal-accounts-design.md` (approved by the user)
- **Plan:** `docs/superpowers/plans/2026-10-24-portal-accounts.md`. 13 tasks; follow it task by task.
- **Dev ports:** API on 8100, web on 5273 (`ELLIS_API=http://localhost:8100 npx vite --port 5273`). The main checkout's 8000/5173 belong to the Cartesia session.
- **Don't edit:** `backend/ellis/api/routes/voice.py`, `backend/ellis/voice/*`, `backend/ellis/config.py`, `backend/prompts/liaison.md`, `frontend/src/applicant/voice.ts`. The only allowed `Chat.tsx` change is the 3 lines in plan Task 11 Step 4.

## Status
- [x] **Task 1: accounts model.** Commit f8f1593: `Account`, `Invitation`, `Case.account_id`, `services/accounts.py`, `tests/test_portal.py`. 61/61 backend tests pass. Not independently reviewed yet.
- [ ] Tasks 2–13: not started. Next is **Task 2 (unified auth routes)**.

Baseline before this work: 57 backend tests passing, `npx tsc --noEmit` clean.

## Rulings that amend the plan (apply them)
- **R1:** Task 3's `test_logged_in_link_attach` checks the case count with `accounts.cases_for(...)` in the DB, not `GET /api/a/account`, which doesn't exist until Task 5.
- **R2:** From Task 3 on, tests that need a clinic link create a fresh case with a helper `new_clinic_case(client) -> (case_id, token)`: log in as `dana@valle.demo` / `ellis-demo`, `POST /api/clinic/cases`, parse the token from `link`, log out. Don't use demo tokens: once Task 8 seeds demo accounts, demo links are already claimed. Browser checks also use a fresh case link.
- **R3:** Task 7's estimate test computes the expected date with `rules.engine.earliest_filing(date(2021,3,4), rule_config())`. Don't assert the literal "2025-12-05" from the plan; it's off by one day.
- **R4:** Task 9 creates `frontend/src/GuestChat.tsx` as a stub: a default export, plus `guestSnapshot()` returning `{answers:{}, transcript:[]}`. Task 10 fills it in, keeping both exports.
- **R5:** The `/conversations` route, the Shell link and the page all land in Task 11. Task 9 only adds `/conversations` to the guest-redirect list.
- **R6:** Clinic sign-up copies the demo clinic's settings shape: `phone` None, retention 90/90, `referral_text` {}, `handles_categories` [arrest, removal, citizenship_claim, fraud, danger].

## How to run
- Backend tests, from `backend/` with the repo `.venv` active (`source ../.venv/bin/activate`): `pytest -q -p no:warnings`
- Frontend type-check, from `frontend/`: `npx tsc --noEmit`
- `backend/.env` was copied into the worktree. It's gitignored, so never commit it.

## Done means
Plan Task 13: all tests pass, tsc is clean, and these flows work in the browser on 8100/5273:
- guest chat → sign up → consent → read-back → Conversations;
- clinic sign-up → invite that applicant by email → the applicant accepts → the clinic sees the case;
- demo logins (`maria@valle.demo` and `dana@valle.demo`, password `ellis-demo`);
- clinic-link sign-up.

The UI must look exactly like the current one: existing CSS classes and markup only.
