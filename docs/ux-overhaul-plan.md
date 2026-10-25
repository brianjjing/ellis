# Ellis UX overhaul plan

Phase 0 described the app as it is. The decisions below are approved and are what Phase 1 implements. Later phases stay as notes.

Where a later phase conflicts with the code, it is marked **Conflict**.

## Decisions

1. **Guest chat** replaces item 1.1 for the logged-out page. `guest.respond` is a guide. General process questions get 1–3 sentences from `backend/prompts/guest_faq.md`, then an offer to do the eligibility check. With `ANTHROPIC_API_KEY` set, a model answers only from that file using `backend/prompts/guest_guide.md`. With no key, keyword matching is used. The check is opt-in: "Want me to check where you stand? I'll ask 2 questions. Your answers stay in this browser until you make an account." `lpr_since` and `married_to_citizen` are asked only after a yes. The same assistant reply is never sent twice in a row. If the visitor asks how Ellis knows something, the reply says Ellis does not know it and is asking. The green-card hint is "You can find it on your green card, next to 'Resident since.'" Every number, fee, or legal threshold in the FAQ is `[VERIFY against current USCIS source]`.

2. **Consent gaps** are part of item 1.2. `documents._apply_doc_fact` stores extracted values as pending (the guest prefill mechanism) when `consent_given` is false, and `record_fact` applies them when consent is recorded. No fact rows before consent. `case_service.stop_now` stores a case-level flag, not a `DEFERRED` fact, and converts it on consent. `evaluate_rules` skips when consent is false. `record_fact` keeps its consent check. The consent screen shows the existing `scripts_en` / `scripts_es` disclosure. "I agree" calls the existing consent endpoint. "Not now" leaves consent off. The voice liaison still speaks the disclosure and does not ask again once consent was given on screen (`LlmLiaison.start` already returns no disclosure when `consent_given` is true). The screen claims only what the code does: conversation text is saved, audio is not, Ellis does not file.

3. **Field labels** come from `backend/config/fields.yaml` through the API (`label_en` or `label_es` by the viewer's language). There is no frontend label map. The reviewer UI is English, so the case payload uses `label_en`. A key missing from `fields.yaml` is title-cased. Those keys are listed under "Labels that are not in fields.yaml" below.

4. **Languages.** The picker lists only what the liaison supports: English and Spanish, with the dialects in `LANGUAGES`. No Vietnamese in the UI. Adding a language needs liaison scripts, field questions, and UI strings. Screens touched in Phase 1 use `t()` in `applicant/i18n.ts`, with strings in `en` and `es`.

5. **Voice** is tap-to-talk. A tap sends talk-down. The turn ends on a second tap or when Ink signals end of turn (`turn.end` in `voice.py`, already used for push-to-talk). `VoiceClient.hold` / `release` stay, because a tap-to-stop still has to send talk-up when Ink has not closed the turn yet. That path is not a second gesture in the UI. Visible text and an `aria-live` region use the existing `VoiceState` values: Connecting…, Listening…, Thinking…, Ellis is speaking, Paused or ended. Tapping the mic while Ellis speaks interrupts it. The signed-in composer toggle reads "Talk" / "Type". The guest composer reads "Sign in to talk with Ellis".

6. **Activity** is pulled forward from Phase 3. A server formatter turns each event kind into one sentence with an actor (Client liaison, Case manager, Paralegal, Docket clerk, QA reviewer, a staff name, or Client). System events with no person use "Ellis". Templates are fixed. Unknown kinds use "Case updated: &lt;field label&gt;" and are listed below.

7. **Form page** stays in Phase 2. The parts list will be built from the sections that exist, not a hardcoded 13. The Continue button stays and will be relabeled "Next: &lt;section name&gt;".

8. **Interview prep** stays in Phase 2. `GET /api/a/case` already returns the applicant's facts (`views.applicant_case` → `facts_panel`, including status). Phase 2 can show confirmed answers read-only. No new API in Phase 1.

9. **Tooling.** `@playwright/test` and `@axe-core/playwright` are frontend devDependencies, with a Playwright config and npm scripts for the existing happy path and for screenshots.

### Labels that are not in fields.yaml

Reviewer field keys use `fields.yaml`. These are not field keys, so they are title-cased in the extraction table (or, for document types, labeled from `extraction/schemas.py` `LABELS_EN`, which the API returns as `document_types`):

`family_name`, `given_name`, `a_number`, `country_of_birth`, `dob`, `resident_since`, `card_expires`, `category`, `side`, `nationality`, `passport_number`, `expiry`, `stamps`, `spouse_1_name`, `spouse_2_name`, `marriage_date`, `place`, `tenant_names`, `city`, `state`, `start`, `end`, `case_no`, `court`, `date`, `disposition`, `amount_paid`, `violation`, `tax_year`, `return_filed`, `filing_status`, `taxpayer_name`, `program`, `beneficiary_name`, `summary`, `quality`, `quality_reasons`.

`a_number`, `dob`, `country_of_birth`, and `nationality` also exist as catalog fields under different keys (`a_number` is a field; the extraction key matches). The extraction table still title-cases the extraction key rather than guessing a catalog key.

### Event kinds on the generic sentence

Every kind the backend emits today has a fixed template in `backend/ellis/services/activity.py`. A kind that is not in that dict uses "Case updated: &lt;field label or title-cased kind&gt;". None of the kinds emitted today are on that fallback.

## 1. Route map

Routing is a hand-rolled History API in `frontend/src/main.tsx` (`navigate`, `pages`). There is no React Router.

| Route | Component | Side | Who sees it |
| --- | --- | --- | --- |
| `/` | `Chat` inside `ApplicantApp` when signed in as an applicant; `GuestChat` when logged out | Client | Applicant home, or the public guide |
| `/form` | `Form` | Client | Signed-in applicant. Guests are sent to `/signin` |
| `/interview` | `Interview` | Client | Signed-in applicant |
| `/reminders` | `Reminders` | Client | Signed-in applicant |
| `/profile` | `Profile` | Client | Signed-in applicant. Not in the phase brief, but it is a real page |
| `/review` | `ReviewPage` in `applicant/Review.tsx` | Client | Signed-in applicant. Sign-off, not the staff review queue |
| `/signin` | `SignIn` | Both | Staff and applicants. `/a/:token` also lands here once the session is known |
| `/signup` | `SignUp` | Both | New applicant or new clinic |
| `/a/:token` | `SignIn` or `SignUp` | Client | Clinic link. It signs the person in; it does not render the old applicant session |
| `/clinic` | `CaseList` inside `ClinicApp` | Reviewer | Staff only. Other roles are redirected |
| `/clinic/cases/:id` | `CaseDetail` | Reviewer | Same tabs for every staff role. Mark ready is reviewer or admin |
| `/clinic/review` | `ReviewQueue` | Reviewer | Reviewer or admin. Hidden from intake in the nav |
| `/clinic/settings` | `Settings` | Reviewer | Admin only |

`ClinicApp` matches `/clinic/cases/:id` with a regex. Unknown client paths fall through to `Chat` or `GuestChat`.

## 2. Component inventory

There is no shared component library. Controls are CSS classes plus markup copied per page.

| Piece | Where it lives | Used by | Duplicates |
| --- | --- | --- | --- |
| Buttons (`.btn`, `.btn.primary`, `.btn.danger`, `.btn.ink`, `.link-btn`, `.icon-btn`) | `styles.css` | Every page | No `Button` component. Hierarchy is class names, applied inconsistently |
| Text inputs (`.input`, `.field`) | `styles.css` | Sign-in, sign-up, clinic forms, chat composer | Chat uses a borderless input inside `.ask`, not `.input` |
| Tabs (`.tabs` / `.tab`) | `styles.css` | `CaseDetail`, `Interview`, `Profile` | Each page owns its tab state. No shared tab component |
| Tables (`.table`) | `app.css` | `CaseList`, `CaseDetail` | One style, two pages |
| Badges (`.badge`, `.pill`, `.demo-tag`, `.status-chip`) | `styles.css`, `app.css` | Shell, case list, case detail, review queue | Three different badge styles |
| Chat bubbles | `Chat.tsx` and `GuestChat.tsx` | Those two pages | Markup is copied. Guest bubbles always show a label; signed-in chat collapses a repeated speaker |
| Nav | `Shell.tsx` (client), `ClinicApp.tsx` (staff) | Client pages; clinic pages | Two sidebars, same visual language, not one component |
| Layout | `.page`, `.side`, `.sidebar`, `.main`, `.bar` | Both sides | `Shell` and `ClinicApp` each assemble it |
| Icons | `icons.tsx` | Chat, form, interview, reminders, guest chat | One sprite map. `talk` is a face with sound waves; `mic` is a microphone |
| Overlays | `applicant/Sheets.tsx` | Upload, secure entry, biographics, referral | Only the signed-in applicant |
| Auth chrome | `SignIn.tsx`, `SignUp.tsx` | `/signin`, `/signup` | Not shared with the chat composer |

`Profile` and `/review` are extra client pages the phase brief does not list. They share `Shell`.

## 3. Styling system

No Tailwind. No CSS modules. Two global stylesheets, imported from `main.tsx`:

- `frontend/src/styles.css` holds the tokens and most rules.
- `frontend/src/app.css` holds clinic tables, the demo tag, and a few later additions.

Tokens are CSS variables on `:root` in `styles.css`:

- Colors: `--paper` `#fbf7ec`, `--sand` `#f2ece0`, `--white`, `--ink` `#0e192b`, `--ink-soft` `#374151`, `--green` `#1e6b5b`, `--green-tint`, `--gold` `#f2c66d`, `--rust` `#b54807`, `--blue` `#1e4fb8`, `--line`, `--line-strong`, `--segment-idle`.
- Type: `--serif` Source Serif 4, `--sans` Atkinson Hyperlegible Next, `--mono` Courier Prime. Fonts are linked from `frontend/index.html`.
- Sizes are per class, not a scale: `.lead` is 17px / 28px, `.h1` is 24px, `.display` is 36px, body inherits the sans. Chat's greeting is an inline 32px serif. Reminders uses an inline 60px serif.
- Spacing is mostly hardcoded padding (`24px`, `28px`, `48px`) and gaps (`8px`, `14px`, `20px`). There is no spacing token.

`:focus-visible` is a 2px ink outline. `prefers-reduced-motion: reduce` turns off the short fade and color transitions.

Uppercase monospace (class `.label` or `.mono`, or a string passed through `.toUpperCase()`):

| Place | Text |
| --- | --- |
| `styles.css` `.label`, `.mono`, `.badge` | The style itself |
| `app.css` `.demo-tag`, table headers, `.mono-s` | Demo tag and clinic table headers |
| `GuestChat.tsx` | `YOU`, `ELLIS` |
| `Chat.tsx` | `YOU`, `YOU · SPOKEN`, `ELLIS`, `ELLIS · OFFICIAL N-400 QUESTION`, `ADD TO N-400`, `SEND TO YOUR CLINIC`, `CHANGE A SETTING · NEEDS YOUR OK`, `CLINIC WILL CHECK`, `NEXT STEP`, past-chat `TODAY` / `VOICE` / `CHAT` |
| `Form.tsx` | `N-400 · APPLICATION FOR CITIZENSHIP`, `PART n · LABEL · n OF n CONFIRMED`, `ELLIS`, zero-padded part numbers |
| `Interview.tsx` | `PRACTICE INTERVIEW · QUESTION n OF n`, `THE OFFICER ASKS`, `YOU SAID`, `ELLIS`, `CIVICS TEST · …`, `THIS PRACTICE: n OF n · NEED 12 OF 20 TO PASS`, `ENGLISH TEST · READING/WRITING` |
| `Reminders.tsx` | Filing date uppercased, `SINCE {date}` |
| `Profile.tsx` | `NEEDS YOUR CLINIC`, `F-01 · NEEDS YOU`, `WITH YOUR CLINIC`, `NOTE FROM YOUR CLINIC` |
| `Shell.tsx` | `LOG IN`, `DEMO DATA` |
| `Sheets.tsx` | `YOUR CLINIC WILL CONTACT YOU` / Spanish equivalent |
| `CaseDetail.tsx` | `STOP-NOW · category`, `ELLIS` / `APPLICANT` on the transcript |
| `ReviewQueue.tsx` | `STOP-NOW`, category names uppercased |
| `styles.css` `.input.code` | Sign-in link code, letter-spaced mono, not a label |

## 4. i18n

There is a small table, not a library.

`frontend/src/applicant/i18n.ts` defines `Lang` as `'es' | 'en'` only. `t(lang, key)` looks up `STRINGS`. `langOf` maps a case locale to `es` or `en`. `LANGUAGES` lists English and Spanish dialects.

`t()` has no callers. The portal pages hardcode English. `langOf` is used to pick a few bilingual bits in `Chat`, `Review`, `Sheets`, and `Profile`. Backend conversation copy is separate: `backend/ellis/voice/scripts_en.yaml` and `scripts_es.yaml`, plus `question_en` / `question_es` on fields.

Vietnamese is not a supported UI or liaison language. Case language is a locale string chosen at case creation (`CaseList`) or on `Profile`.

Screens whose strings are hardcoded English, and would stay untranslated if Phase 1 only covers the screens it touches: `SignIn`, `SignUp`, all of `/clinic`, `Profile` beyond the language names, and most of `Interview` and `Reminders`.

## 5. Chat pipeline, and the repeated green-card question

The conversation in the bug is the logged-out page, not the signed-in voice session.

`GuestChat` (`frontend/src/GuestChat.tsx`) is what a visitor sees at `/`. Its greeting is "I help people get ready to apply for U.S. citizenship" and the input placeholder is "Ask anything, in any language". Sending calls `POST /api/guest/chat` with the messages and the previous `answers` object.

`guest.chat` in `backend/ellis/api/routes/guest.py` trims the last 30 messages and calls `guest.respond` in `backend/ellis/services/guest.py`. That function does not read `backend/prompts/`. Nothing is written to the database. The reply is a fixed script.

`respond` does this:

1. Take the latest message whose `who` is `"you"`.
2. If it hits a stop keyword, return `STOP_REPLY` and stop.
3. Otherwise look at the first unanswered item in `QUESTIONS`. The only items are `lpr_since`, then `married_to_citizen`.
4. If the pending key is `lpr_since`, try `parse_value("lpr_since", "date", last)`. A greeting or a question does not parse as a date, so `answers` is unchanged.
5. Set `reply` to the question string for the still-unanswered key.

That question string is exactly: "When did you become a permanent resident? The date on your green card is fine."

So "hi, how does the process work?" is ignored, and the function asks for the green-card date. "how do you know what the date on my green card is" also does not parse as a date, `lpr_since` is still missing, and line 36 returns the same `nxt` string again. There is no check for a repeated reply, and no branch that explains that Ellis does not already know the date.

The responsible function is `respond` in `backend/ellis/services/guest.py`. The route in front of it is `chat` in `backend/ellis/api/routes/guest.py`. A comment in `respond` says a Claude-backed guide (`prompts/guest_guide.md`) could replace this later. That prompt file does not exist.

The signed-in path is different and did not produce this wording. `Chat.tsx` opens `VoiceClient.start`, which connects to `WS /api/a/voice`. `VoiceSession.run` in `backend/ellis/api/routes/voice.py` constructs `LlmLiaison` (`backend/ellis/voice/llm_liaison.py`). That class loads `backend/prompts/liaison.md`, speaks the disclosure from `scripts_en.yaml` or `scripts_es.yaml` until consent, and then uses the model. The green-card sentence is not in those files.

## 6. Voice

Signed-in chat starts Cartesia in `VoiceClient.start` (`frontend/src/applicant/voice.ts`). It opens `WS /api/a/voice` and sends `{type:'start', language, locale, voice, disclosure_shown}`. The server (`voice.py`) starts Ink-2 STT and Sonic TTS when keys exist, and an `LlmLiaison`.

The microphone (`icons.tsx` `mic`) is push-to-talk. Pointer down calls `hold()`; pointer up calls `release()`. Holding sends `{type:'talk', down:true}`, streams PCM16, and cuts off Ellis. Releasing submits the turn. The placeholder says "Hold on the green microphone button to the right and talk!" The button has `aria-label="Hold to talk"`. While the pointer is down, the placeholder is "Listening… let go to send."

The face with sound waves (`icons.tsx` `talk`) is not a listening indicator. On the signed-in composer it is "Talk instead", shown only in typing mode, and it switches back to push-to-talk. On the guest composer the same icon is "Log in to talk with Ellis" and sends the visitor to sign-in. It does not start a microphone.

`VoiceState` is `'idle' | 'connecting' | 'speaking' | 'listening' | 'thinking' | 'ended'`. `Chat` stores it. The only user-visible voice state is the hold placeholder, plus a text notice if the mic is denied or Sonic is down. There is no "Thinking…", "Ellis is speaking", or "Paused" label, and no `aria-live` region for those states. The thread itself is `aria-live="polite"`. Reduced motion is global in `styles.css`; nothing voice-specific animates.

Interview prep does not use Cartesia. `Interview.tsx` uses the browser `SpeechRecognition` and `speechSynthesis`, and it saves nothing. Its file header says study and mock interview have no Case API yet.

## 7. Consent and fact writes

Logged-in voice: if `consent_given` is false, `LlmLiaison.start` returns the disclosure script and waits. Agreeing goes through the model's `record_fact` tool, which calls `case_service.record_fact`. The disclosure text is in `scripts_en.yaml` `disclosure`. It names Ellis, says it is not a lawyer, says the clinic reviews the case, says the text is saved and the audio is not, and asks "Do you agree to continue?" There is no separate screen with "I agree" and "Not now". `Profile` has a setting, "Consent to talk with Ellis", whose button calls `POST /api/a/consent` (`applicant.py` `set_consent`).

`case_service.record_fact` refuses any field other than `consent` when `consent_given` is false, with `consent_required` / 409. `test_at1_consent_first` covers the tool route. Guest answers are not facts until consent: `accounts.apply_prefill` runs inside `_record_consent`, and `test_prefill_applied_on_consent` checks that `lpr_since` is absent before that.

Paths that write a fact:

| Path | Consent check |
| --- | --- |
| `case_service.record_fact` | Yes, except the `consent` field itself |
| `tools.record_fact` | Calls `record_fact` |
| `liaison.py` (scripted liaison, still in the tree; the web socket uses `LlmLiaison`) | Calls `record_fact` |
| `llm_liaison.py` tool handler | Calls `record_fact` |
| `applicant.set_consent` | Writes only the consent fact |
| `accounts.apply_prefill` | Runs only after consent is recorded |
| `demo.simulate_answers` | Writes consent first when the script includes it, then other facts through `record_fact` |
| `clinic.demo_autofill` | If consent is missing, it injects `consent: True` into the synthetic answers and then calls `simulate_answers` |
| `documents._apply_doc_fact` | **Conflict.** Inserts facts with `_insert_fact` and does not call `record_fact`. A green card uploaded before consent can store `lpr_since`, `dob`, and name fields |
| `case_service.stop_now` | **Conflict.** Writes `DEFERRED` facts through `_insert_fact` with no consent check |
| `case_service.evaluate_rules` | Writes `eligibility_basis` through `_insert_fact`. It runs when facts change, so it normally follows a consented write, but it does not check consent itself |

The guest guide does not write facts. It does collect `lpr_since` and `married_to_citizen` in browser memory (`guestSnapshot`), and sign-up sends that object. Those values become hedged facts only after consent. **Conflict with Phase 1.2:** the public guide already asks for those two personal answers before an account exists.

What the disclosure may claim, because the code does it: conversation text is stored as `Utterance` rows; audio is not stored; Ellis does not file. Do not add privacy claims beyond that.

## 8. Field labels

Keys and English/Spanish labels live in `backend/config/fields.yaml`. `catalog.field_def`, `label_en`, and `label_es` in `backend/ellis/services/catalog.py` read them.

Examples already in the catalog, which do not match the wording proposed in Phase 1.5:

| Key | Existing `label_en` | Phase 1.5 wording |
| --- | --- | --- |
| `lpr_since` | Resident since | Permanent resident since |
| `name.given` | Given name(s) | First name |
| `eligibility_basis` | Eligibility basis | (same idea) |

`green_card` is a document type, not a field key. The upload dropdown in `CaseDetail` prints the raw type with underscores turned into spaces.

The applicant form and the reviewer Facts tab already receive `label` from `catalog.label_en` / `label_es` (`views.fact_groups`, `views.fact_history`). Places that still show keys: the ready-gate `fields` list, document extraction tables, the document-type `<select>`, gap rows (reason text only; no label field is returned), and review-item `field` when `facts` is empty.

**Conflict:** a second label map in a frontend file will drift from `fields.yaml`. The catalog is already the one map. Phase 1 should pass `label_en` through the API where a key is still shown, and fall back to a title-cased key only when `field_def` returns nothing.

## 9. Demo-only controls

`Clinic.is_demo` is the switch. The seeded clinic `cl_valle` is `is_demo=true` (`backend/seed/load.py`). A clinic created at sign-up is `is_demo=false`.

The only action control is "Simulate remaining intake (demo)" on `CaseDetail`, rendered when `d.clinic.is_demo`. It calls `POST /api/clinic/cases/:id/demo_autofill`, which 403s unless the clinic is a demo, then writes `seed/scripts.py` `SCRIPTS` through `simulate_answers`. Those facts are marked `provenance.simulated`.

Other demo chrome, not actions: "Synthetic demo data" in `ClinicApp`, "DEMO DATA" in `Shell`, "Simulated clinic reviewer (demo)" in `ReviewQueue`, and " · simulated" appended to fact provenance in `views._fact_row`. `patient_mode` is not demo-only. It is a case setting ("Patient mode", "patient" pill) for a slower voice.

## 10. Agent activity on the case page

`GET /api/clinic/cases/:id` is `views.clinic_case_detail`. `CaseDetail` reads that one payload.

| UI | Data | What it actually shows |
| --- | --- | --- |
| Activity | `events`: last 400 `Event` rows (`kind`, `payload`, `actor_type`, `actor`, `ts`) | A table. Filter is by `actor_type`. The payload column is `JSON.stringify` |
| Memos | `memos`: `Memo` rows, kinds `qa`, `status`, `note` | `body_md` inside `<pre>`. Empty copy is "None yet." |
| Task board | `tasks`: last 100 `Task` rows, with `agent_label` from `AGENT_LABELS_EN` | A row per task: label, title, kind, time. No status grouping. An empty list renders only the heading |
| Briefing | `briefing`: latest `Briefing.body` | Raw `JSON.stringify` under "Latest briefing (liaison queue)" |
| Facts | `facts` from `fact_history` | Label, value, status, provenance sentence |
| Documents | `documents` plus `gaps` | Uploaded files and extraction keys. Gaps are reason plus status |
| Review | `review_items` from `review_item_view` | Category, speed, status, `facts` or `field`. Stop-now items have a banner and no detail |
| Transcript | `transcript`: `Utterance` rows, omitted when clinic retention is `none` | Speaker, time, text. Stop-now text is stored as `[STOP:…]` and shown as `[STOP]` |
| Packet | `packets` | Built when the applicant signs. Approve stays on the header (`Mark ready`), not here |

There is no separate work log. Agent work that becomes an event, a task, a memo, or a review item is all that exists. Current English agent labels are "Case coordinator", "Document checker", "Deadline tracker", and "Quality check", not the playbook names Paralegal, Docket clerk, and QA reviewer.

## 11. Tests

Backend, from `backend/`:

```bash
uv run pytest
```

`pyproject.toml` sets `testpaths = ["tests"]` and `addopts = "-q"`. Files: `test_acceptance.py` (AT1–AT20, including consent-first), `test_portal.py` (guest chat, prefill-on-consent, accounts), `test_rules.py`, `test_agent.py`.

Frontend: `npm run e2e` is `node e2e/happy-path.cjs`. That file requires Playwright and is written to be run with a global install (`NODE_PATH=$(npm root -g)`). Playwright is not in `frontend/package.json`. `frontend/e2e/gate.check.ts` is a separate check, also not wired as an npm script. Neither uses axe. Shots go to `frontend/e2e-shots/`, which is gitignored.

Pages those tests touch: the happy path signs into `/clinic`, opens a case, clicks "Simulate remaining intake (demo)", opens `/clinic/review`, and signs as the applicant. `test_portal.py` hits `/api/guest/chat` and consent. `test_acceptance.py` hits `record_fact` and the scripted liaison. Interview, Reminders, Form, and GuestChat have no UI test.

**Conflict with later phases:** "take Playwright screenshots" and "axe via Playwright" need a dependency that is not installed. Adding Playwright, and axe if the check is in-repo, has to be called out when it happens.

## 12. Phase checklist, files, and conflicts

### Phase 1

| Item | Files | Conflict or block |
| --- | --- | --- |
| 1.1 Answer the user, then ask; never repeat; explain "how do you know" | `backend/ellis/services/guest.py`, `backend/tests/test_portal.py`. The signed-in model is `llm_liaison.py` plus `prompts/liaison.md` and should get the same rules if the product promise is for both chats | The reported bug is only the guest script. Do not look for this sentence in the liaison prompt |
| 1.2 Consent screen before intake; API refuses facts without consent | New UI in front of `Chat.tsx` / `GuestChat.tsx`. Disclosure copy already in `scripts_en.yaml` / `scripts_es.yaml`. API refusal already in `record_fact` and `test_at1_consent_first`. Clinic name is `clinic.name` on the case view and in the liaison config | Close the holes in `documents._apply_doc_fact` and `stop_now` if the acceptance bar is really "no path". Guest chat already solicits `lpr_since` before an account. "Not now" has no backend state today; declining consent is `consent.declined` and ends the scripted liaison |
| 1.3 Guided start, language, chips | `GuestChat.tsx`, `Chat.tsx`, `i18n.ts`, `Shell.tsx` | No Vietnamese. Do not invent a 15-minute duration; nothing in the code supports it. Use "a few short sessions". `t()` exists and is unused |
| 1.4 Voice as the primary control | `Chat.tsx`, `icons.tsx`, `voice.ts`, `styles.css` | Guest chat cannot open the mic; talking requires an account. States exist on the client and are mostly not rendered. Push-to-talk already interrupts Ellis |
| 1.5 Readable briefing, human labels, demo menu | `CaseDetail.tsx`, `views.py` (`clinic_case_detail`, `gate_status`), `catalog.py` | Do not add a second label map. Facts already use catalog labels. `lpr_since` is "Resident since", not "Permanent resident since". Demo actions are the one autofill button plus several tags |

### Phase 2

| Item | Files | Status |
| --- | --- | --- |
| Mobile nav, hide locked items, 18px body, sentence case | `Shell.tsx`, `styles.css`, `app.css`, every client page that uses `.label` | **Done** (commits 87f44cb, 42fb55b) |
| Save-conversation prompt once | `GuestChat.tsx` | **Done** (commit 42fb55b) |
| Chat labels and read-back values | `Chat.tsx` | **Done** — sentence case throughout (commit 42fb55b) |
| N-400 as a review list | `Form.tsx` | **Done** — mono header removed, part label sentence-cased, continue → "Next: {label}" / "Done", upload promoted to primary (commit 9a15fdc) |
| Interview: civics spoken first; hide 0 of 0; explain 12 of 20; English word diff | `Interview.tsx` | **Done** — "Answer out loud" primary, choices behind toggle, score hidden until first answer, [VERIFY] comment added, word-level diff (commit 520a3b7) |
| Reminders next-step card and stepper | `Reminders.tsx` | **Done** — roadmap stepper from `data.roadmap.stages/current`, future items replaced with one line (commit 2481e48) |
| Profile sentence case | `Profile.tsx` | **Done** (commit d4fa61a) |
| Empty and error states | Each client page | Not yet addressed beyond existing `e.message` surfaces |

### Phase 3

| Item | Files | Status |
| --- | --- | --- |
| Client link column, "Extra support" pill+tooltip, "stop now" lowercase | `CaseList.tsx` | **Done** (commit 28916dd) |
| Close dialog names case; "Extra support" toggle; transcript sentence case; stop-now lowercase | `CaseDetail.tsx` | **Done** (commit 28916dd) |
| STOP-NOW and category uppercase → sentence case | `ReviewQueue.tsx` | **Done** (commit 28916dd) |
| (a) Case detail header: Mark ready primary, secondary actions grouped, Close in ⋯ menu | `CaseDetail.tsx`, `app.css` | **Done** (commit c820a97) |
| (b) Ready gate: blockers grouped by type, tab links, collapsible field lists | `CaseDetail.tsx`, `app.css` | **Done** (commit c820a97) |
| (c) Activity tab: actor filter, links from each entry to related fact/doc/review/memo | `CaseDetail.tsx`, `app.css` | **Done** (commit c820a97) |
| (d) Facts tab: status badges (Confirmed/Disputed/Proposed), document source links | `CaseDetail.tsx` | **Done** (commit c820a97) |
| (e) Documents tab: expected-document checklist (green card, passport + open gaps) | `CaseDetail.tsx` | **Done** (commit c820a97) |
| (f) Review tab: severity badge, plain description, linked sources, next-step text | `CaseDetail.tsx`, `ReviewQueue.tsx` | **Done** (commit c820a97, a6ad4a1) |
| (g) Memos: task board as one card per agent, QA/status/note memos formatted | `CaseDetail.tsx`, `app.css` | **Done** (commit c820a97) |
| (h) Cases list: sort needs-attention first, "Needs you" badge+filter, relative times | `CaseList.tsx`, `api.ts`, `app.css` | **Done** (commit 64c63cb) |
| (i) Form page: section list with status per section and Answer/Edit actions | `Form.tsx`, `app.css` | **Done** (commit 774a099) |
| (j) Reminders: next-step card from real case state | `Reminders.tsx` | **Done** (commit 2481e48) |
| (k) Empty states for every client and reviewer tab | `CaseDetail.tsx`, `CaseList.tsx`, `ReviewQueue.tsx`, `Form.tsx` | **Done** (commits c820a97, 64c63cb, a6ad4a1, 774a099) |
| Screenshots at 390px + 1280px (all case tabs, cases list, form, reminders) | `e2e/screenshots.spec.ts` | **Done** — 33 shots, 0 axe violations |

### Phase 4

Copy, contrast, focus, and one button hierarchy touch `styles.css`, `app.css`, and the pages above. Axe is not installed. Legal numbers already in the UI that must be marked `[VERIFY against current USCIS source]` and not edited: the civics line "NEED 12 OF 20 TO PASS" in `Interview.tsx`, and any day-count the rules engine already speaks (early filing, presence). Do not add a 15-minute estimate.

Untranslated after a minimal Phase 1 i18n pass, unless that phase grows: clinic app, sign-in, sign-up, profile, interview, reminders, review-and-sign.
