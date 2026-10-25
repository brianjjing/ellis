# Ellis Portal: Accounts, Guest Chat, Self-Serve Clinics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Ellis from link-only and seeded-staff-only into one real, role-based application. Guests chat at `/`. Applicants and clinics sign themselves up. Clinics invite existing applicants by email and the applicant accepts. All of it looks exactly like the current UI.

**Architecture:** A new `account` table holds applicant identities. Independent cases live in a hidden system clinic (`cl_independent`), so every clinic-scoped query keeps working. Account sessions reuse the existing applicant cookie shape (`{"kind":"applicant","case_id",…}` plus `account_id`), so the voice and stream WebSockets don't change. Account logic lives in one new service (`services/accounts.py`) with thin route files. The frontend adds an auth context and a few pages built only from existing CSS classes and markup.

**Tech Stack:** FastAPI, SQLAlchemy 2, pydantic 2, argon2 (existing), pytest; React 19 + TypeScript + Vite (existing history router). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-24-portal-accounts-design.md`

## Global Constraints

- No new dependencies, backend or frontend.
- Visuals: only existing classes from `frontend/src/styles.css` and `frontend/src/app.css`, and markup copied from existing pages. No new colors, fonts or component styles. A new CSS rule is allowed only to combine existing tokens (`var(--…)`), and only in `app.css`.
- Don't edit files owned by the parallel Cartesia session: `backend/ellis/api/routes/voice.py`, `backend/ellis/voice/*`, `backend/ellis/config.py`, `backend/prompts/liaison.md`, `frontend/src/applicant/voice.ts`. The single allowed touch to `frontend/src/Chat.tsx` is Task 11 Step 4 (3 lines in `nextStep`).
- Cookies: applicant `ellis_a` = `auth.sign({"kind": "applicant", "case_id": <active case id>, "account_id": <id or absent>})`; staff `ellis_s` unchanged. Both httpOnly, samesite lax, max_age 12 h, set exactly as `routes/applicant.py:43` and `routes/clinic.py:41` do.
- Passwords are at least 8 characters, hashed with `auth.hash_password`. Emails are stored `strip().lower()`. One email belongs to at most one identity, across `account` and `staff_user`.
- Signup and login are rate-limited with `auth.rate_limited(f"auth:{ip}", limit=20)`, and the guest chat with `auth.rate_limited(f"guest:{ip}", limit=30)`.
- Guest conversations are never persisted server-side and never logged. Stop-list words are never stored raw (`[STOP:<category>]` only). Numbers go through `keywords.redact_numbers`.
- Copy is English-first. The exact strings below are fixed by the spec and must be used verbatim:
  - `NEUTRAL_INVITE` = "If someone has an Ellis account with that email, they'll see your invitation. Otherwise, create a case and send them a link."
  - `LINK_TAKEN` = "This link belongs to another account. Ask your clinic for help."
  - `NEEDS_CLINIC` = "This part needs a clinic or attorney"
  - `DRAFT_WARNING` = "Have a clinic or attorney review this before filing"
- The independent clinic: `id="cl_independent"`, `name="Independent"`, `is_demo=False`, no staff. Create it lazily via `accounts.independent_clinic(s)`.
- Schema changes rely on dev reseed (`drop_all`/`create_all`). For the one new column on an existing table (`cases.account_id`), also add `ALTER TABLE cases ADD COLUMN IF NOT EXISTS account_id VARCHAR(40)` in the `if is_postgres():` block of `db.create_all`.
- Every existing test (57 at baseline) keeps passing. Run backend tests from `backend/` with `uv run pytest -q -p no:warnings`, and type-check the frontend from `frontend/` with `npx tsc --noEmit`.
- The worktree's dev servers run on API port `8100` and web port `5273` (`ELLIS_API=http://localhost:8100 npx vite --port 5273`), so the Cartesia session's 8000 and 5173 stay untouched.

## Review Focus

1. **A clinic invites an email that has no account, or that belongs to staff.** It must get the same neutral reply and the same status code as a real account, with no invitation visible to anyone. Test: Task 6 `test_invite_reply_is_neutral`.
2. **An applicant declines, or never answers, an invitation.** Nothing moves: no case is created in that clinic, and their independent case's `clinic_id` is unchanged. Test: Task 6 `test_nothing_moves_before_accept`.
3. **A guest message containing a stop-list phrase or an A-number is imported at sign-up.** It must be stored as `[STOP:<cat>]` or redacted, never raw. Test: Task 4 `test_guest_import_redacts`.
4. **Someone opens a clinic link that is already attached to another account** (forwarded link). Refused with `LINK_TAKEN`; after staff detach the case, the next link works. Test: Task 3 `test_link_taken_then_detach`.
5. **A staff cookie and an applicant cookie are both present** (one browser, two logins). `/api/auth/me` must report the role of the most recent login, and logout must clear both. Test: Task 2 `test_login_replaces_other_role`.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `backend/ellis/db.py` | modify | `Account`, `Invitation`, `Case.account_id`, Postgres ALTER |
| `backend/ellis/services/accounts.py` | create | identities, independent clinic, link attach, invitations, transfer, prefill, transcript import, cookies |
| `backend/ellis/services/guest.py` | create | stateless guest guide: stop check, eligibility extraction, estimate, reply |
| `backend/prompts/guest_guide.md` | create | Claude prompt for the guest guide |
| `backend/ellis/api/routes/auth.py` | create | `/api/auth/*`: signup, login, logout, me |
| `backend/ellis/api/routes/guest.py` | create | `/api/guest/chat` |
| `backend/ellis/api/routes/applicant.py` | modify | `/api/a/account`, `/api/a/cases/{id}/activate`, `/api/a/link`, `/api/a/invitations/*`, `/api/a/conversations` |
| `backend/ellis/api/routes/clinic.py` | modify | `/api/clinic/invitations`, `/api/clinic/cases/{id}/detach_account`; old `/login` and `/logout` delegate to `auth` |
| `backend/ellis/api/app.py` | modify | include `auth` and `guest` routers |
| `backend/ellis/services/case_service.py` | modify | `_record_consent` calls `accounts.apply_prefill` |
| `backend/ellis/services/views.py` | modify | `applicant_case`: `independent`, `needs_clinic`, `account` |
| `backend/seed/load.py` | modify | demo applicant accounts |
| `backend/tests/test_portal.py` | create | all backend tests for this plan |
| `frontend/src/auth.tsx` | create | `AuthProvider`, `useAuth()`, `goSignIn(next)` |
| `frontend/src/main.tsx` | modify | role routing, `/signup`, `/conversations`, guest at `/` |
| `frontend/src/SignIn.tsx` | modify | unified email/password sign-in, link/code secondary |
| `frontend/src/SignUp.tsx` | create | role choice, applicant/clinic forms, link sign-up |
| `frontend/src/GuestChat.tsx` | create | logged-out chat (Chat markup, guest backend) |
| `frontend/src/Shell.tsx` | modify | guest variant (locked links, Log in/Sign up), Conversations link, clinic banner |
| `frontend/src/Conversations.tsx` | create | past sessions for the active case |
| `frontend/src/Profile.tsx` | modify | cases switcher, invitations, sign out via `/api/auth/logout` |
| `frontend/src/applicant/ApplicantApp.tsx` | modify | invitation card |
| `frontend/src/applicant/Review.tsx` | modify | independent case: draft + `DRAFT_WARNING` |
| `frontend/src/Chat.tsx` | modify (3 lines) | `nextStep` for independent cases |
| `frontend/src/clinic/ClinicApp.tsx` | modify | logged out → `/signin?next=/clinic`; remove `Login` |
| `frontend/src/clinic/CaseList.tsx` | modify | "Add client by email", invited rows |
| `frontend/src/clinic/CaseDetail.tsx` | modify | "Detach account" |

---

### Task 1: Accounts data model and core service

**Files:**
- Modify: `backend/ellis/db.py`
- Create: `backend/ellis/services/accounts.py`
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces (db):
  - `Account`: `id` (`new_id("ac")`), `email` String(200) unique, `name` String(200), `password_hash` String(300), `active_case_id` String(40) nullable, `created_at`.
  - `Case.account_id`: String(40), FK `account.id`, nullable, indexed.
  - `Invitation` (table `invitation`): `id` (`new_id("iv")`), `clinic_id` (indexed), `email` String(200) (indexed), `invited_by` String(40), `status` String(20) ∈ `pending|accepted|declined`, `case_id` String(40) nullable, `created_at`, `decided_at` nullable.
- Produces (`accounts.py`):

```python
INDEPENDENT_ID = "cl_independent"
class AccountError(Exception):          # .status: int, .code: str, .message: str
    def __init__(self, status: int, code: str, message: str): ...
def email_taken(s: Session, email: str) -> bool                 # account OR staff_user
def independent_clinic(s: Session) -> Clinic                    # get-or-create, constants above
def create_account(s: Session, name: str, email: str, password: str) -> Account
    # AccountError(400,"weak_password") if len<8; (409,"exists") if email_taken; (400,"bad_email") if no "@"
def authenticate(s: Session, email: str, password: str) -> Account | StaffUser | None   # inactive staff → None
def create_independent_case(s: Session, acct: Account, language: str = "en-US") -> Case
    # Case(clinic_id=INDEPENDENT_ID, account_id, first/last split from acct.name on first space, state="consent_pending")
    # + emit case.created, publish_briefing({"queue": []}, proposed_by="case_api"); sets acct.active_case_id
def cases_for(s: Session, acct: Account) -> list[Case]          # newest first
def active_case(s: Session, acct: Account) -> Case | None       # active_case_id if still owned, else newest
def applicant_cookie(acct: Account | None, case: Case) -> str   # auth.sign({"kind":"applicant","case_id":case.id, **({"account_id":acct.id} if acct else {})})
def is_independent(case: Case) -> bool
```

- [ ] **Step 1: Write failing tests** in `tests/test_portal.py` (use the `seeded` fixture):
  - `test_create_account_and_independent_case`: create account "Ana Pérez" / `ana@x.test` / `password1`. Its independent case has `clinic_id == "cl_independent"`, `first_name == "Ana"`, `last_name == "Pérez"`, and `account_id` set, and `active_case(...)` is that case.
  - `test_email_unique_across_staff_and_accounts`: `create_account(..., "dana@valle.demo", ...)` raises `AccountError` with `status == 409`.
  - `test_weak_password_rejected`: `"short"` → `AccountError.code == "weak_password"`.
  - `test_authenticate_both_kinds`: returns an `Account` for the new applicant and a `StaffUser` for `dana@valle.demo`/`ellis-demo`, and `None` for a wrong password.
- [ ] **Step 2: Run `uv run pytest tests/test_portal.py -q` and confirm it fails** (import error).
- [ ] **Step 3: Implement the models, the Postgres ALTER and `accounts.py`.**
- [ ] **Step 4: Run `uv run pytest -q -p no:warnings` and confirm everything passes** (57 plus the new tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(accounts): applicant accounts, invitations table, independent clinic"`

### Task 2: Unified auth routes

**Files:**
- Create: `backend/ellis/api/routes/auth.py`
- Modify: `backend/ellis/api/app.py` (include the router)
- Modify: `backend/ellis/api/routes/clinic.py` (`/login` and `/logout` call the same helpers so old clients keep working)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `POST /api/auth/signup`. Body: `{kind: "applicant"|"clinic", name, email, password, clinic_name?: str, link_token?: str, guest?: {answers: dict, transcript: [{who: "you"|"ellis", text}]}}`.
    - applicant without `link_token` → `create_account` + `create_independent_case`.
    - applicant with `link_token` → Task 3 attach, no independent case.
    - clinic → `Clinic(name=clinic_name, is_demo=False, settings={"phone": None, "retention": {"transcripts_days": 90, "closed_case_delete_days": 90}})` + `StaffUser(role="admin")`. `clinic_name` is required for clinics (400 `"clinic_name"`).
    - `guest` → Task 4 (ignored for clinic).
    - Sets the right cookie, deletes the other role's cookie, and returns `me`.
  - `POST /api/auth/login {email, password}` → 401 `bad_credentials` "Wrong email or password." on failure. Otherwise it sets one cookie, deletes the other, and returns `me`.
  - `POST /api/auth/logout` → deletes both cookies → `{"ok": true}`.
  - `GET /api/auth/me` → one of:
    - `{"kind": "guest"}`
    - `{"kind": "applicant", "account": {"id", "name", "email"} | null, "case_id"}`
    - `{"kind": "staff", **clinic.me_payload(...)}`

    Staff cookie wins if both are somehow present and valid. A link-only applicant cookie yields `account: null`.
  - `accounts.AccountError` maps to `err(e.status, e.code, e.message)`.

- [ ] **Step 1: Write failing tests** using the `client` fixture:
  - `test_signup_applicant_sets_cookie`: signup returns kind `applicant`; `/api/a/case` returns 200 with `clinic.name == "Independent"`.
  - `test_signup_clinic_creates_admin`: signup as a clinic called "Casa Legal" → `/api/clinic/me` returns role `admin` and clinic name "Casa Legal"; `/api/clinic/cases` returns `[]`.
  - `test_login_routes_by_role`: login as `dana@valle.demo` → `me.kind == "staff"`; logout → `me.kind == "guest"`.
  - `test_login_replaces_other_role`: sign up an applicant, then log in as Dana → `me.kind == "staff"` and `/api/a/case` returns 401; then log in as the applicant → `me.kind == "applicant"` and `/api/clinic/me` returns 401.
  - `test_wrong_password_401`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement `auth.py` and wire it up.**
- [ ] **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(auth): one signup/login/logout/me for applicants and clinic staff"`

### Task 3: Clinic link path and staff detach

**Files:**
- Modify: `backend/ellis/services/accounts.py`
- Modify: `backend/ellis/api/routes/applicant.py` (add `POST /api/a/link`)
- Modify: `backend/ellis/api/routes/clinic.py` (add `POST /api/clinic/cases/{case_id}/detach_account`)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces:
  - `attach_link(s: Session, acct: Account, token: str) -> Case`. Uses `auth.resolve_link`.
    - Expired → `AccountError(410, "link_expired", "This link has expired. Ask your clinic for a new one.")`.
    - Invalid → `(404, "link_invalid", "This link isn't valid. Ask your clinic for a new one.")`.
    - `case.account_id` set to another account → `(409, "link_taken", LINK_TAKEN)`.
    - Otherwise sets `case.account_id`, `acct.active_case_id = case.id`, emits `link.opened` and `account.attached` `{account_id}`, and returns the case.
  - `link_preview(s: Session, token: str) -> dict` → `{"first_name", "last_name", "clinic_name"}`, with the same errors, but without marking the link used.
  - `GET /api/auth/link/{token}` returns `link_preview`, for prefilling the sign-up form.
  - `POST /api/a/link {token}` requires an account cookie (401 otherwise), reissues the cookie for the attached case, and returns `views.applicant_case`.
  - `POST /api/clinic/cases/{case_id}/detach_account` (roles `ALL`, `clinic_case` scope) sets `case.account_id = None`, emits `account.detached`, and returns `{"ok": true}`.
  - `clinic_case_detail` and `case_row` gain `"account_email": str | None`.

- [ ] **Step 1: Write failing tests:**
  - `test_signup_with_link_attaches_without_independent_case`: signup with `link_token="demo-ana"` → `me.case_id == "c_ana"`, and the account owns exactly one case.
  - `test_logged_in_link_attach`: an applicant signs up (independent), then `POST /api/a/link {"token": "demo-jorge"}` → the cookie now points at `c_jorge`, and `GET /api/a/account` (Task 5) lists two cases.
  - `test_link_taken_then_detach`: account A claims `demo-rosa`. Account B posting the same token gets 409 with `message == LINK_TAKEN`. Dana detaches `c_rosa`. Admin issues a new link via `POST /api/clinic/cases/c_rosa/link`. B claims the new token → 200.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement, including signup's `link_token` branch in Task 2's route.**
- [ ] **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(accounts): claim clinic links into accounts; staff can detach"`

### Task 4: Guest work carries into the new account

**Files:**
- Modify: `backend/ellis/services/accounts.py`
- Modify: `backend/ellis/services/case_service.py` (`_record_consent`, value True branch, after `set_state`)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces:
  - `PREFILL_FIELDS = {"lpr_since": "lpr_since", "married_to_citizen": None}`. When `married_to_citizen is True`, the prefill writes `marital.status="married"` and `spouse.citizenship_status="us_citizen"`.
  - `save_prefill(s: Session, case: Case, answers: dict) -> None` keeps only known keys with valid values (`lpr_since` as an ISO date string `YYYY-MM-DD` or `YYYY-MM`, `married_to_citizen` as a bool) into `case.settings["prefill"]` (reassign the dict).
  - `apply_prefill(s: Session, case: Case) -> int` pops `settings["prefill"]`. For each value it calls `cs.record_fact(s, case, field, value, hedge=True, source="spoken", actor="guest_import", actor_type="system", provenance={"guest": True})`, ignores `CaseError` per field, and returns the count saved. Hedged facts become unconfirmed, so the existing read-back confirms them.
  - `import_guest_transcript(s: Session, case: Case, transcript: list[dict]) -> str | None`:
    - Creates a `CallSession(channel="guest", started_at=ended_at=now())` and returns its id.
    - Inserts `Utterance` rows: speaker `applicant` for `who=="you"`, `liaison` for `who=="ellis"`.
    - Applicant text with `keywords.stop_hit` → `"[STOP:<cat>]"` and `redacted=True`; otherwise `keywords.redact_numbers` when `has_sensitive_number`.
    - Caps at 200 messages and 2,000 characters each. Raises no flags. Returns `None` for an empty transcript.
  - `_record_consent` (True branch) calls `accounts.apply_prefill(s, case)` as a local import, after `set_state` and before `evaluate_rules`.
  - The signup route calls `save_prefill` and `import_guest_transcript` on the case it attached or created.

- [ ] **Step 1: Write failing tests:**
  - `test_prefill_applied_on_consent`: signup with `guest.answers={"lpr_since": "2021-03-04", "married_to_citizen": True}`; no `lpr_since` fact exists before consent. Then `record_fact(case, "consent", True)` → the `lpr_since` fact has value `"2021-03-04"` and `hedge` True, and `marital.status == "married"`.
  - `test_guest_import_redacts`: transcript with a stop-list phrase (the one `test_at8` uses) and "my A number is 123456789" → the stored utterance texts contain `"[STOP:"` and no `"123456789"`, and the session channel is `"guest"`.
  - `test_bad_prefill_values_dropped`: `{"lpr_since": "yesterday", "hack": 1}` → `settings.get("prefill") in (None, {})`.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and confirm it passes** (AT1 still proves consent comes first).
- [ ] **Step 5: Commit** — `git commit -m "feat(accounts): guest answers prefill the case on consent; guest transcript imported redacted"`

### Task 5: Account endpoints: cases, switching, conversations

**Files:**
- Modify: `backend/ellis/api/routes/applicant.py`
- Modify: `backend/ellis/services/views.py` (`applicant_case`)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces:
  - `deps.account_of(request, s) -> Account | None` reads `account_id` from the applicant cookie.
  - `GET /api/a/account` (account cookie required, 401 otherwise) → `{"account": {"id", "name", "email"}, "active_case_id", "cases": [{"id", "clinic_name", "independent", "state", "created_at"}], "invitations": [{"id", "clinic_name", "created_at"}]}`. Invitations are pending ones whose `email == account.email`.
  - `POST /api/a/cases/{case_id}/activate` → 404 unless the case belongs to the account. Sets `active_case_id`, reissues the cookie, returns `views.applicant_case`.
  - `GET /api/a/conversations` → `{"sessions": [{"id", "channel", "started_at", "messages": [{"who": "you"|"ellis", "text", "ts"}]}]}` for the active case, newest session first, sessions without utterances omitted. The clinic retention rule applies: an empty list when `transcripts_days == "none"`.
  - `views.applicant_case` gains:
    - `"independent": bool`
    - `"needs_clinic": bool` (independent and either `case_blocked` or any open stop-now review item)
    - `"account": {"name", "email"} | None`

    For independent cases `"case_blocked"` is reported as `False`, so the frontend never says "Your clinic will contact you". `needs_clinic` replaces it.

- [ ] **Step 1: Write failing tests:**
  - `test_account_lists_cases_and_activate`: an account with an independent case plus the `demo-jorge` link → two cases; activate the independent one → `/api/a/case` `case_id` matches.
  - `test_cannot_activate_foreign_case`: activate `c_maria` → 404.
  - `test_conversations_active_case_only`: signup with a guest transcript (one guest session) → `/api/a/conversations` returns one session. After `POST /api/a/link demo-jorge` → zero sessions.
  - `test_independent_stop_now_sets_needs_clinic`: independent case, consent, then `applicant_turn` with the AT8 stop phrase via `cs.applicant_turn` → `/api/a/case` has `needs_clinic` True and `case_blocked` False.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(applicant): account cases, switching, conversations; independent-case flags"`

### Task 6: Clinic invitations with applicant acceptance, and case transfer

**Files:**
- Modify: `backend/ellis/services/accounts.py`
- Modify: `backend/ellis/api/routes/clinic.py`
- Modify: `backend/ellis/api/routes/applicant.py`
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces:
  - `invite(s: Session, staff: StaffUser, email: str) -> Invitation | None`. A no-op (returns `None`) when the email has no account, when a pending invitation from this clinic already exists, or when the account already owns a case in this clinic. Otherwise it creates a pending invitation. The caller always replies `{"ok": true, "message": NEUTRAL_INVITE}` with 200.
  - `transfer_case(s: Session, case: Case, clinic: Clinic) -> None`. For every mapped table class whose columns include both `case_id` and `clinic_id`, plus `Case` itself, it updates `clinic_id` for rows with that `case_id`, using `update()` statements built from `Base.registry.mappers`. It emits `case.transferred` `{"from", "to"}`.
  - `accept_invitation(s: Session, acct: Account, inv_id: str) -> Case` → 404 unless pending and `inv.email == acct.email`.
    - If the account has an independent case: `transfer_case` into the clinic.
    - Else: a new `Case(clinic_id=inv.clinic_id, account_id=acct.id, …)` like `create_independent_case`.
    - Sets `inv.status="accepted"`, `inv.case_id`, `decided_at`, and `acct.active_case_id`.
  - `decline_invitation(s, acct, inv_id) -> None` sets `status="declined"`.
  - Routes:
    - `POST /api/clinic/invitations {email}` (roles `ALL`).
    - `GET /api/clinic/invitations` → `{"invitations": [{"id", "email", "status", "created_at"}]}` for this clinic. It returns only invitations that exist, so emails without accounts never appear.
    - `POST /api/a/invitations/{id}/accept` reissues the cookie and returns `views.applicant_case`.
    - `POST /api/a/invitations/{id}/decline` → `{"ok": true}`.

- [ ] **Step 1: Write failing tests:**
  - `test_invite_reply_is_neutral`: Dana invites `nobody@x.test`, then a real applicant's email, then `sam@valle.demo` → all three replies are identical, with status 200. `GET /api/clinic/invitations` lists only the real applicant.
  - `test_nothing_moves_before_accept`: an independent applicant with one uploaded document (`POST /api/a/documents` with `seed/documents/ana_passport.png`). Dana invites them. Before accepting, the case's `clinic_id == "cl_independent"` and `/api/clinic/cases` doesn't include it. Decline → still unchanged.
  - `test_accept_moves_everything`: same setup, accept → the case's `clinic_id == "cl_valle"`, and every `Document`, `Fact`, `Event`, `Utterance` and `VaultValue` row for that case has `clinic_id == "cl_valle"`. Dana's `/api/clinic/cases/<id>` returns 200 with the document listed.
  - `test_accept_without_independent_case_creates_new`: an account that only holds the `demo-jorge` case is invited by clinic `cl_other` (log in as `staff@other.demo`) → accepting creates a new case in `cl_other`, and `c_jorge` stays in `cl_valle`.
  - `test_cannot_accept_someone_elses_invitation` → 404.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(clinic): invite by email; applicant accepts; independent work transfers"`

### Task 7: Guest guide backend

**Files:**
- Create: `backend/ellis/services/guest.py`
- Create: `backend/prompts/guest_guide.md`
- Create: `backend/ellis/api/routes/guest.py`
- Modify: `backend/ellis/api/app.py`
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces:
  - `POST /api/guest/chat {messages: [{who: "you"|"ellis", text}], answers: dict}`. Messages are capped at the last 30, and texts at 2,000 characters. Returns `{"reply": str, "answers": dict, "estimate": {"earliest_filing": "YYYY-MM-DD", "window_open": bool} | null, "stop": bool}`.
  - `guest.respond(messages: list[dict], answers: dict, today: date) -> dict`, in order:
    1. If the last applicant text hits `keywords.stop_hit` → reply `STOP_REPLY` and `stop: true`, answers unchanged.
    2. Extract answers from the last applicant text with the existing NLU, `ellis.voice.english` (`parse_value("lpr_since", "date", text)` for the date, `yes_no(text)` for married-to-citizen when that was the last question asked). These modules are read-only imports, not edits.
    3. With `ANTHROPIC_API_KEY`, ask Claude (`settings.liaison_model`, max_tokens 400) with `prompts/guest_guide.md` + the messages + the answers JSON, and get `{"reply"}` back. Otherwise use the scripted reply: the next unanswered question from `QUESTIONS`, or a summary when all are answered.
    4. `estimate` = `rules.engine.earliest_filing(date.fromisoformat(lpr_since + "-01" if 7 chars else lpr_since), rule_config())` with `window_open = estimate <= today`. Append `MARRIED_NOTE` to the reply when `married_to_citizen` is True.
  - Constants in `guest.py`:
    - `QUESTIONS = [("lpr_since", "When did you become a permanent resident? The date on your green card is fine."), ("married_to_citizen", "Are you married to a U.S. citizen?")]`
    - `STOP_REPLY = "That's something to talk through with a clinic or attorney before you go further. I can't help with it here, but a clinic can, and it's confidential."`
    - `MARRIED_NOTE = " If you've been married to and living with a U.S. citizen for 3 years, you may qualify sooner; a clinic can confirm."`
  - The prompt: Ellis is a guide, not a lawyer. Give general process information only, never advice on a specific person's legal situation. Keep answers short and plain. Suggest signing up to save progress and start the N-400, and recommend working with a clinic.
  - The route rate-limits, never logs bodies, and writes nothing to the DB.

- [ ] **Step 1: Write failing tests** (`client` fixture, no API key in tests):
  - `test_guest_asks_then_estimates`: an empty conversation's reply contains "permanent resident". After answering "since March 4 2021", `answers.lpr_since == "2021-03-04"` and `estimate.earliest_filing == "2025-12-05"` (5 years minus 90 days, per rule config; if the rule config's early-filing days differ, compute the expected value from `rule_config()` in the test).
  - `test_guest_stop_topic`: the AT8 stop phrase → `stop` True and the reply equals `STOP_REPLY`.
  - `test_guest_writes_nothing`: the `Event`, `Utterance` and `CallSession` row counts are unchanged after three calls.
- [ ] **Step 2: Run them and confirm they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "feat(guest): stateless guest guide with eligibility estimate and stop-list safety"`

### Task 8: Demo seed accounts

**Files:**
- Modify: `backend/seed/load.py` (after the cases are created)
- Test: `backend/tests/test_portal.py`

**Interfaces:**
- Produces: accounts `maria@valle.demo`, `jorge@valle.demo`, `ana@valle.demo` and `rosa@valle.demo`, password `DEMO_PASSWORD`, each owning its demo case (`account_id` set, `active_case_id` set). Update the printed summary line to mention applicant logins.

- [ ] **Step 1: Write the failing test** `test_demo_applicant_login`: login as `maria@valle.demo` / `ellis-demo` → `me.case_id == "c_maria"`.
- [ ] **Step 2: Run it and confirm it fails.** **Step 3: Implement.** **Step 4: Run the full suite and confirm it passes.**
- [ ] **Step 5: Commit** — `git commit -m "chore(seed): demo applicants get real logins"`

### Task 9: Frontend auth, routing, sign-in and sign-up

**Files:**
- Create: `frontend/src/auth.tsx`
- Create: `frontend/src/SignUp.tsx`
- Modify: `frontend/src/main.tsx`
- Modify: `frontend/src/SignIn.tsx`
- Modify: `frontend/src/clinic/ClinicApp.tsx`

**Interfaces:**
- Produces in `auth.tsx`:

```ts
export type Me = { kind: 'guest' } | { kind: 'applicant'; account: { id: string; name: string; email: string } | null; case_id: string } | ({ kind: 'staff' } & StaffMe)
export function AuthProvider({ children }: { children: ReactNode })   // loads /api/auth/me once; exposes refresh()
export function useAuth(): { me: Me | null; refresh: () => Promise<Me> }  // me null while loading
export function goSignIn(next: string): void                          // navigate(`/signin?next=${encodeURIComponent(next)}`)
export function safeNext(raw: string | null, fallback: string): string // only same-origin paths starting with "/" and not "//"
```

- Routing in `main.tsx`, wrapped in `<AuthProvider>`:
  - Loading → blank `<div className="page" />`, as today.
  - `/signin` → `SignIn`. `/signup` → `SignUp`. `/a/:token` → `SignUp` with `token` if guest, or a call to `POST /api/a/link` then `navigate('/')` if applicant (on `link_taken` show the error on `SignIn`'s error line).
  - `/clinic*`: staff → `ClinicApp`; otherwise `goSignIn(path)`.
  - Guest: `/` → `GuestChat` (Task 10); any applicant page (`/form`, `/interview`, `/reminders`, `/profile`, `/review`, `/conversations`) → `goSignIn(path)`.
  - Applicant: today's `pages` table plus `/conversations` inside `ApplicantApp`.
  - Staff at a non-clinic path → `navigate('/clinic', true)`.
- `SignIn` keeps the current markup (header, `.signin`, `.card`) and becomes:
  - Email and Password fields, a primary "Log in" button, then `<div className="or">or</div>` (a new `app.css` rule using existing tokens; copy it from the approved mockup), then a strong button "I have a link or code from a clinic" that reveals today's Code input and resolves to `/a/<code>`.
  - `p.switch`: "New to Ellis? Create an account" → `/signup?next=…`.
  - The heading is "Log in to Ellis", or "Log in to start your N-400" when `next=/form`, "Log in to see your conversations" for `/conversations`, and "Log in to continue" for other `next` values.
  - After login: staff → `/clinic`; applicant → `safeNext(next, '/')`.
- `SignUp` reuses the same frame:
  - Two `.opt` radio rows: "Applying for U.S. citizenship" (default) and "Part of a legal clinic". The clinic option adds a "Clinic name" field.
  - Fields: Your name, Email, Password (hint "At least 8 characters").
  - With `token`: the clinic option is hidden, name is prefilled from `GET /api/auth/link/{token}`, the heading is "Join {clinic_name} on Ellis", and there's an "Already have an account? Log in" link to `/signin?next=/a/<token>`.
  - Sends `guest` data from `GuestChat`'s exported `guestSnapshot()` (Task 10). Afterwards it calls `refresh()` and navigates as `SignIn` does.
- `ClinicApp`: delete the `Login` component. When `me === null`, call `goSignIn(path)`. Logout calls `/api/auth/logout`, then `refresh()`, then `navigate('/')`.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Type-check** — `cd frontend && npx tsc --noEmit`. Expected: no output.
- [ ] **Step 3: Browser check** on the worktree servers (API 8100, web 5273):
  - Guest `/form` → sign-in page with heading "Log in to start your N-400".
  - Log in as `maria@valle.demo` → lands on `/form`.
  - Log out → `/`. Log in as `dana@valle.demo` → `/clinic`.
  - Sign up a new clinic → empty Cases list with the clinic name in the sidebar.
  - Open `/a/demo-rosa` logged out → "Join Clínica Comunitaria del Valle (demo) on Ellis" with name "Rosa".
- [ ] **Step 4: Commit** — `git commit -m "feat(web): one sign-in, sign-up for applicants and clinics, role routing"`

### Task 10: Guest chat and guest shell

**Files:**
- Create: `frontend/src/GuestChat.tsx`
- Modify: `frontend/src/Shell.tsx`

**Interfaces:**
- Produces:
  - `Shell` accepts `guest?: boolean`. When it's true, it doesn't call `useCase()`, renders "Chat with Ellis" as current, and renders N-400 form, Interview prep and Reminders as `navlink` items with a trailing `<span className="badge">LOG IN</span>` that call `goSignIn(href)`. The foot shows `p.small` "Work at a clinic? Staff sign in" → `/signin?next=/clinic`.
  - Applicant `Shell` gains a "Conversations" navlink (`/conversations`) after "Chat with Ellis". `Section` gets `'conversations'`.
  - `GuestChat` copies `Chat.tsx`'s render structure: `main.chat`, `header.bar`, `.chat-body`, `.convo`, `.thread`, `.msg`/`.you` bubbles, `.composer`, `form.ask`.
    - The bar's `.btns` hold `<button className="btn">Log in</button>` (→ `goSignIn('/')`) and `<button className="btn primary">Sign up</button>` (→ `/signup`).
    - The greeting is "{greeting()}. I help people get ready to apply for U.S. citizenship.", followed by a `p.lead.soft` line: "Ask me anything about the process, or tell me a little about yourself and I'll check where you stand."
    - After every Ellis reply it shows a `.hint`-style line: "Create a free account to save this conversation and start your N-400. Sign up". The `.hint` rule from the approved mockup goes in `app.css`.
    - The mic and clip buttons call `goSignIn('/')`.
    - State is module-level (`let guest = { msgs: [], answers: {} }`) so it survives navigation but not a reload, and is never written to storage. `export function guestSnapshot(): { answers: Record<string, unknown>; transcript: { who: 'you' | 'ellis'; text: string }[] }`.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Type-check** — `npx tsc --noEmit`.
- [ ] **Step 3: Browser check.** As a guest at `/`, type "I got my green card March 4 2021" → Ellis replies with an earliest-filing date. Click Sign up → finish → land on `/`. `/conversations` shows the guest session. After giving consent in Chat, Ellis reads back the residence date.
- [ ] **Step 4: Commit** — `git commit -m "feat(web): logged-out guest chat with locked pages and sign-up carry-over"`

### Task 11: Applicant additions: conversations, invitations, independent cases

**Files:**
- Create: `frontend/src/Conversations.tsx`
- Modify: `frontend/src/Profile.tsx`
- Modify: `frontend/src/applicant/ApplicantApp.tsx`
- Modify: `frontend/src/applicant/Review.tsx`
- Modify: `frontend/src/Chat.tsx` (Step 4 only)
- Modify: `frontend/src/Shell.tsx` (clinic banner)

**Interfaces:**
- Consumes: Task 5 and 6 endpoints and the new `applicant_case` fields.
- Produces:
  - `Conversations`: `Shell active="conversations"`, `header.bar` with `h1.h1` "Conversations". Each session is a `.card` whose label reads `{DATE} · {CHAT|VOICE|BEFORE SIGN-UP}` (from `channel`). Messages render with the same `.msg`/`.you` markup as `Chat`. Empty state: `p.lead.soft` "Your conversations with Ellis will show up here."
  - `ApplicantApp`: when `/api/a/account` has invitations, render a `.card-stack` card styled like `ReferralCard`: "{clinic_name} wants to add you" / "Your answers and documents will move to {clinic_name} so they can review them." / buttons "Accept" (primary) and "Decline". On accept, reload.
  - `Shell` (applicant, `data.independent`): above `children`, a dismissible card. Use the `.notice` rule from mockup 1, added to `app.css`. Copy: title "We strongly recommend working with a legal clinic", body "You can prepare everything here. Before you file, a clinic or attorney should review it. When a clinic adds you, your work moves with you." Buttons "Find a clinic" (an `<a target="_blank">` to `https://www.justice.gov/eoir/recognized-organizations-and-accredited-representatives-roster-state-and-city`) and "Not now" (hides it until reload). When `data.needs_clinic`, the title becomes `NEEDS_CLINIC` and the card can't be dismissed.
  - `Profile`: a "Your cases" section (one row per case: clinic name or "On your own", state, a "Switch" button that calls activate then `location.assign('/')`) and pending invitations with Accept/Decline. Sign out calls `/api/auth/logout`, then `refresh()`, then `navigate('/')`.
  - `Review` (independent): instead of sign-off, a `.card` with `DRAFT_WARNING` as `h2.h3`, a `p.lead.soft` "Ellis isn't a law firm. Without a clinic, there's no review or filing packet.", and the existing "Download a draft for my professional" button behavior (`/api/a/professional_draft`).
- [ ] **Step 1: Implement everything above except `Chat.tsx`.**
- [ ] **Step 2: Type-check.**
- [ ] **Step 3: Browser check:**
  - The independent applicant sees the banner; Find a clinic opens the roster.
  - `/review` shows the draft and warning, and the PDF downloads.
  - Dana invites that email; the applicant sees the invitation card; Accept → banner gone, Profile shows the Valle case, Dana's list includes it.
- [ ] **Step 4: The `Chat.tsx` touch (coordinated with the Cartesia session).** In `nextStep`, before `const sec = …`, insert:

```ts
  if (data.independent && data.needs_clinic) return { title: 'This part needs a clinic or attorney', note: 'Keep going with the rest. A clinic can help with this part.' }
```

  And replace the final "Your clinic is reviewing" return for independent cases with:

```ts
  if (!sec && data.independent) return { title: 'Take your answers to a clinic', note: 'Have a clinic or attorney review this before filing', go: '/review', label: 'Get my draft' }
```

  Expect a merge conflict here when the Cartesia branch lands. Both edits are additive.
- [ ] **Step 5: Type-check, then commit** — `git commit -m "feat(web): conversations, invitations, independent-case banner and draft"`

### Task 12: Clinic additions: invite by email, detach

**Files:**
- Modify: `frontend/src/clinic/CaseList.tsx`
- Modify: `frontend/src/clinic/CaseDetail.tsx`

**Interfaces:**
- Consumes: Task 3 and 6 endpoints.
- Produces:
  - `CaseList`: next to "New case", a `btn md` "Add client by email" opening the same inline-card pattern as the "New case" form. It has one email field and "Send invitation". After submitting, it shows `p.small` with the reply's `message` (always `NEUTRAL_INVITE`). Below the table, if `GET /api/clinic/invitations` has `pending` items, add a "Invited" `h2.h3` with a small table: email, status, sent.
  - `CaseDetail`: in the header actions, when `d.case.account_email` is set, show `p.small` "Account: {email}" and a `btn danger` "Detach account". Confirm with `window.confirm('Detach this account? The person will need a new link to get back in.')`, then POST and reload.
- [ ] **Step 1: Implement. Step 2: Type-check.**
- [ ] **Step 3: Browser check:** an invite shows the neutral message; a pending invite is listed; detach works on `c_maria` after Maria logs in.
- [ ] **Step 4: Commit** — `git commit -m "feat(clinic-web): invite clients by email; detach accounts"`

### Task 13: Whole-app verification

- [ ] **Step 1:** `cd backend && uv run pytest -q -p no:warnings`. Expected: everything passes.
- [ ] **Step 2:** `cd frontend && npx tsc --noEmit`. Expected: no output.
- [ ] **Step 3: Fresh reseed and full walkthrough in the browser** on 8100/5273, with screenshots:
  - guest chat → sign up → consent → read-back of the guest date → Conversations;
  - clinic sign-up → invite that applicant → accept → the clinic sees the case and its documents;
  - demo logins for Maria and Dana;
  - a link sign-up for Rosa.
- [ ] **Step 4:** List any visual departures found against the current UI and fix them, or report them.
