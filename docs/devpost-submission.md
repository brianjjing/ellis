# Ellis

Ellis is a Voice-first agentic immigration assistant software to guide people through the process of naturalization. Ellis has the user 

## Inspiration

[YOUR INPUT NEEDED — the real story: what prompted this, who it's for, the moment that made it click. Don't let me guess at this one.]

## What it does

An applicant opens a link on their phone and talks to Ellis in Spanish or English — no typing, no forms, just a conversation at their own pace. Every fact they state gets checked against the N-400's real requirements as they go: hedge on a date and Ellis asks to read it back before trusting it; mention something that needs a document and it's added to a gap list; say something that touches a stop-now issue (arrest, removal, fraud) and the session halts for attorney review immediately, no AI judgment call involved.

Behind that single conversation, four AI staff agents work the case the way a real legal team would — one coordinating the file, one checking documents against stated facts, one tracking deadlines and filing windows, one doing a last quality pass before anything reaches a human. None of them talk to the applicant directly, and none of them write anything to the case without going through a typed, authority-checked API — they propose, the Case API validates and writes with provenance.

The clinic's attorneys and accredited reps see everything the agents flagged, review it, and only then does the applicant sign off. Ellis never tells someone they "qualify." It never files anything. [YOUR INPUT NEEDED — add the specific demo beat you want in the write-up, e.g. the hedged-date email-confirmation moment, if you want it called out here.]

## How we built it

**Cartesia carries the entire voice path.** Ink-2 streaming speech-to-text (over websocket, with turn detection driving barge-in — no push-to-talk button needed to know when someone's done speaking) feeds a Claude-driven liaison, which replies through Sonic streaming text-to-speech with word-level timestamps — those timestamps are what let an applicant interrupt mid-sentence and have playback cut exactly where they started talking, not at the next audio chunk boundary. Consent disclosures and stop-now safety scripts are the one exception: those are locked and finish playing no matter what, by design.

**Creao runs the staff team.** Four separately hosted agents — case manager, document paralegal, docketing clerk, QA reviewer — each get their own Creao app, their own authority limits enforced in our own code (not just trusted from the prompt), and their own playbook adapted from Harvey's Legal Agent Benchmark task patterns. Our backend calls each agent's Creao API directly per run, waits for it to finish, and translates whatever shape that agent's engine returns into one typed proposal envelope our Case API can validate. [YOUR INPUT NEEDED — name the specific Creao capability you want to highlight, e.g. the Gmail MCP connector work, if you want that called out explicitly rather than folded into the agent description.]

Everything else is a straightforward FastAPI + React stack: a pure rules engine (no model ever computes a date or a deadline — that's deterministic code, versioned), a sandboxed document-extraction worker with no DB credentials, and Postgres (SQLite in dev) holding the whole audit trail as an append-only event log.

## Agents

| Agent | Owns | Can propose |
|---|---|---|
| Case manager | Eligibility basis, cross-fact conflicts, the top-priority question queue, attorney escalations | briefing, task, memo (status), review item |
| Document paralegal | Document checks against stated facts, the evidence gap list | gap, gap close, task (finding), review item, evidence, doc checks |
| Docketing clerk | Filing windows, presence-day math, upcoming deadlines | deadline, task (finding) |
| QA reviewer | A structured QA pass before sign-off, challenge questions on weak spots | task, review item, memo (qa), review note |

| Agent | Creao app ID | Run share link |
|---|---|---|
| Case manager | `[FILL IN]` | `[FILL IN]` |
| Document paralegal | `[FILL IN]` | `[FILL IN]` |
| Docketing clerk | `[FILL IN]` | `[FILL IN]` |
| QA reviewer | `[FILL IN]` | `[FILL IN]` |

*(Never put a real API key in this file — app IDs and public run-share links only.)*

## Challenges we ran into

[LEFT BLANK — fill in]

-
-
-

## Accomplishments that we're proud of

- A real, live-tested integration with all four Creao agents against real case data, through the actual automatic dispatcher — not just isolated test scripts.
- Caught and root-caused a genuine bilingual bug (a hardcoded Spanish key meant the conversation could silently switch languages mid-session) before it ever reached a demo.
- The system structurally cannot let an AI-found candidate (a document match, a found email) become a confirmed fact without the applicant hearing it read back and confirming out loud — that's enforced by the schema, not a prompt instruction anyone could forget.
- [YOUR INPUT NEEDED — add the ones that felt real to you; don't want to overclaim ones I didn't watch you hit.]

## What we learned

- [YOUR INPUT NEEDED]

## What's next

- Per-user Gmail OAuth, so each applicant connects their own inbox instead of the whole demo sharing one hardcoded account.
- A real standalone MCP server for the email-search/escalation tools, so they're callable by more than just our own backend.
- [YOUR INPUT NEEDED — anything else on the real roadmap, e.g. the USCIS fee-schedule lookup tool we deliberately pinned for later.]

## Built with

Cartesia · Creao · Anthropic Claude · FastAPI · SQLAlchemy · PostgreSQL · React · Vite · TypeScript

## Try it out

- GitHub repo: `[FILL IN]`
- Live demo: `[FILL IN, if applicable]`

## Submitted to

CalHacks — `[FILL IN exact track name]`

## Team

Aarush Narayanan · Saachi Surana · Brian Jing · Abhay Bhat
