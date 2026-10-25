# Ellis Portal: Accounts, Guest Chat, Self-Serve Clinics — Design

Date: 2026-10-24 · Status: approved in conversation ("Yes! Go ahead and start development") · Branch: `portal`

## Intent

Today Ellis only works for people a clinic has already set up: applicants get in through a private
clinic link, and clinic staff accounts come from a demo seed or an admin invite. Nobody can arrive
cold and start. The goal is one real application, not a set of test links: anyone lands on Ellis,
talks to it straight away, creates an account when they want to keep going, and clinics can sign
themselves up and take people on.

The flow should feel like ChatGPT: you arrive in a conversation, not on a login wall. "Log in" and
"Sign up" are always visible, and anything that needs an account sends you to log in, then brings you
back to what you asked for.

**Look:** the frontend must look exactly like the current UI (same CSS, components, typography,
sidebar, chat). New screens are built from existing classes in `styles.css` / `app.css` and existing
page markup. Mockups the user approved are in `.superpowers/brainstorm/*/content/portal-entry*.html`
(local only).

## Who uses it

- **Guest:** anyone, not logged in. Lands on the Chat page.
- **Applicant:** a person preparing their own naturalization application. Owns an account. May or
  may not be connected to a clinic.
- **Clinic staff:** intake, reviewer, admin. Belong to exactly one clinic (unchanged).

## Goals

1. **Guest conversation at `/`.** Today's Chat page and sidebar, with Log in and Sign up in the
   header bar. Sidebar pages that need an account (N-400 form, Interview prep, Reminders, and the new
   Conversations page) stay visible, marked "LOG IN". Clicking one goes to
   `/signin?next=<that page>`.
2. **What the guest chat does:** Ellis acts as a guide, not a form-filler. It answers general
   questions about the naturalization process and runs a short eligibility check (when they became a
   permanent resident, whether they're married to a U.S. citizen, long trips abroad). It gives an
   earliest-filing estimate from the existing rules engine. The sensitive-topic rules stay on: a
   stop-list topic gets the "please talk to a clinic" response, and Ellis never gives legal advice.
   Nothing about a guest conversation is stored on the server; it lives in the browser tab only.
3. **One sign-in page for everyone.** Email and password, plus a secondary "I have a link or code from
   a clinic" path. The account decides where you land: applicants go to `next` or `/`, staff go to
   `/clinic`. The separate clinic login screen goes away; `/clinic` while logged out redirects to
   `/signin?next=/clinic`.
4. **One sign-up page.** "I am applying for U.S. citizenship" or "I am part of a legal clinic".
   Applicants give name, email and password. Clinics also give a clinic name, which creates the clinic
   and makes the person its first admin. That admin invites staff from Settings, as today.
5. **Guest work carries into a new account.** At sign-up the guest's eligibility answers become
   answers on the new case for Ellis to confirm with a read-back ("you said you've had your green card
   since 2021, is that right?"), and the guest transcript becomes the first conversation in their
   history.
6. **An applicant without a clinic can use everything** (Chat, N-400 form, uploads, Interview prep,
   Reminders, Profile). A strong but non-blocking recommendation to work with a clinic is always
   available. At the end there is no clinic review and no file-ready packet: they get the existing
   "draft for your own professional" PDF with a clear "take this to a clinic or attorney before
   filing".
7. **Clinic link path.** Opening `/a/<token>`:
   - Logged out: the sign-up page, applicant option pre-chosen and name pre-filled from the case, plus
     "Already have an account? Log in". Finishing either attaches that clinic case to the account.
   - Logged in as an applicant: attaches immediately.
8. **Clinic adds an existing person by email, and the person accepts.** In the clinic's case list,
   "Add client by email" creates a pending invitation.
   - The clinic always sees the same neutral reply: "If someone has an Ellis account with that email,
     they'll see your invitation. Otherwise, create a case and send them a link." It never reveals
     whether an account exists. Pending invitations show in the clinic's list as "Invited".
   - The applicant sees "<Clinic> wants to add you" with Accept and Decline (user decision: an accept
     step is required).
   - On Accept: if they have an independent (no-clinic) case, that case and everything in it moves to
     the clinic. Otherwise a new case is created for them in this clinic. Nothing moves before Accept.
9. **Conversations.** A logged-in applicant can see their past sessions with Ellis (transcripts, text
   only) on a Conversations page.

## Non-goals (this round)

- Email sending of any kind: no verification, password reset, or invite emails. "Add by email" is a
  lookup, not a message.
- Social or OAuth login, phone or SMS login.
- Voice for guests. The mic button in the guest chat says "Log in to talk with Ellis"; voice stays
  for logged-in applicants.
- Pulling an independent case's work into a clinic case on the **link** path. Only "add by email"
  moves work. A person who already has independent work and then opens a clinic link keeps both
  cases and can switch between them in Profile.
- Changes to the voice liaison, Cartesia gateway or liaison prompts.

## Anti-goals (would make this a failure even if it works)

- Any visual departure from the current UI: new colors, fonts, component styles, or a separate
  "portal" look.
- A guest's words stored on the server before they create an account, or stop-list words stored raw
  anywhere.
- Breaking the existing acceptance tests (AT1–AT20) or the demo seed.
- Collisions with the parallel Cartesia session. It owns `backend/ellis/api/routes/voice.py`,
  `backend/ellis/voice/*`, `backend/ellis/config.py` (voice settings), `backend/prompts/liaison.md`,
  `frontend/src/applicant/voice.ts` and the voice parts of `frontend/src/Chat.tsx`. This work must not
  edit those files beyond unavoidable one-line touches, each called out in the plan.

## Constraints and decisions already made

- Backend: FastAPI + SQLAlchemy + SQLite/Postgres as today. Auth uses existing argon2 hashing
  (`auth.hash_password`) and HMAC-signed httpOnly cookies (`auth.sign`). No new dependencies.
- Frontend: React + Vite + existing history-API router (`navigate`, `data-nav` links). No router
  library, no CSS framework.
- Same-origin, cookie-based auth, as today.
- English-first copy, matching the latest commit ("default everyone to English"). Applicant pages
  that already switch on `langOf(data)` keep doing so.

## Decisions marked as the designer's call (check these)

1. **Applicants get their own `account` table** (email, password, name). Staff stay in `staff_user`.
   One email can't be both: sign-up checks both tables, and login looks in both.
2. **Independent cases live in a hidden system clinic** (`cl_independent`, `is_demo=False`, no
   staff). This keeps every existing clinic-scoped query working unchanged. "Moving a case to a
   clinic" rewrites `clinic_id` on the case and every row that carries both `case_id` and
   `clinic_id`.
3. **An account can hold several cases** (at most one independent case, plus one per clinic). The
   app works on one "active" case at a time: the most recently attached, switchable in Profile.
4. **Guest answers are stored on the new case as `settings.prefill`** and turned into hedged,
   unconfirmed facts at the moment the applicant gives consent (consent is required before any fact,
   AT1), so the existing read-back flow confirms them. No change to the liaison itself.
5. **The guest transcript is imported as a `session` with channel `guest`.** Applicant turns go
   through the same stop-list replacement and number redaction as live turns. Importing raises no
   flags.
6. **The guest chat brain:** Claude, with a guide prompt, when `ANTHROPIC_API_KEY` is set. Otherwise
   a scripted fallback that asks the three eligibility questions in order. The earliest-filing
   estimate uses the engine's 5-year rule (`rules.engine.earliest_filing`). The 3-year
   married-to-a-citizen path is mentioned as "you may qualify sooner; a clinic can confirm", because
   the engine doesn't model it.
7. **Conversations is its own page (`/conversations`) in the sidebar,** rather than rebuilding
   Chat's "Past chats" panel, so `Chat.tsx` (owned by the Cartesia session) stays untouched.
8. **Demo seed:** demo applicants get accounts (`maria@valle.demo` etc., password `ellis-demo`) so
   the demo works through the real login. The existing link-token cookie exchange (`/api/a/session`)
   stays for the tests and backwards compatibility, but the UI no longer sends anyone through it
   without an account.
9. **The applicant cookie keeps its current shape** (`ellis_a` = signed `{"kind": "applicant", "case_id": <active case>}`) plus `account_id`. `voice.py` and `/api/a/stream` read `kind`/`case_id` straight from this cookie, so keeping the shape means neither file changes. Switching the active case re-issues the cookie.
10. **Passwords:** at least 8 characters.
11. **Independent case with a stop-now topic or a blocking flag.** Those sections pause. Instead of "Your clinic will contact you", the applicant sees "This part needs a clinic or attorney" with Find a clinic. Every other section keeps working. The professional draft PDF stays downloadable behind a warning ("Have a clinic or attorney review this before filing"). The case never goes to `ready` or `signed` without a clinic.
12. **Signing up through a clinic link** does not create an independent case. The guest prefill and transcript go into that clinic case. Signing up without a link creates one independent case.
13. **A link whose case is already attached to a different account is refused** ("This link belongs to another account. Ask your clinic for help."). Clinic staff get a "Detach account" action on the case, which frees it to be claimed by the next link they send. That is also the recovery path for a forgotten password until email exists.
14. **Conversations shows sessions for the active case only.** Clinics already see only their own case's transcript. Login and sign-up are rate-limited per IP with the existing
   `auth.rate_limited`.

## Left to the builder

Endpoint names and payload shapes, component breakdown, how the guest transcript is kept in the tab
(in-memory module state, as `Chat.tsx` does today), banner placement details within the approved
mockups, and test structure.
