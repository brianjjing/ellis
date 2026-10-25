# Canonical field names: what the Supabase migration needs to preserve

For whoever merges the Supabase migration branch, and whoever continues the Creao agent integration.
Read this before either of you touches field names.

## Why this exists

While live-testing the four Creao-hosted staff agents (`creao` branch) against real `c_maria` case
data today, three of the four agent engines (`case_master.py`, `docket_engine.py`, `qa_review.py` —
each a separate Python script bundled into its own Creao app) turned out to look up **their own
canonical field names**, which don't match Ellis's own field keys (`backend/config/fields.yaml`).
Two agents actually caught this themselves mid-run and self-reported exactly which names they
expected, rather than silently producing wrong output. That's how this list was built — from real
agent output, not guesswork.

## The decision (my call — flag it if you disagree)

**Keep Ellis's own field names (`lpr_since`, `dob`, `a_number`, `name.given`, etc.) exactly as they
are. Do not rename them to match Creao's canonical names.** Instead, maintain one explicit alias table
that translates Ellis's names into whatever each Creao engine expects, at the point where we build the
bundle we send to Creao.

Why: renaming would touch `fields.yaml` plus every consumer across the app — the liaison's scripts,
`catalog.py`, the frontend's field labels, the rules engine, years of existing tests. That's real
surface area, for a rename whose only beneficiary is three external scripts we don't control the
source of. A translation table is one small, reviewable file, independent of whichever database sits
underneath, and survives if Creao's engines ever change their own naming again.

Where it lives right now: `_CANONICAL_ALIASES` in `backend/ellis/agents/backends.py`. That's fine for
a hackathon; if this grows past four agents' worth of aliases, move it to its own file
(`backend/ellis/agents/creao_field_aliases.py`) so it's not buried inside the dispatch code.

## What this means for the Supabase migration specifically

1. **Don't rename any existing field keys during the migration.** The alias table maps *current* Ellis
   key names → Creao canonical names. If the migration renames `lpr_since` to something else at the
   database level, the alias table silently goes stale and every agent run quietly breaks again,
   exactly like it did before we found this today.
2. **The migration can restructure the underlying tables however it wants.** The alias table operates
   on `build_context()`'s *output* (the `ctx["facts"]` dict — `{field_key: {value, status, source,
   hedge, ...}}`), not on raw database columns. As long as `build_context()` keeps producing that same
   shape after the migration, this is completely insulated from whatever Supabase schema sits under it.
3. **If the migration adds genuinely new fields** that these agents also expect, check this alias table
   first before deciding the new Ellis-side key name — see the list below for names already confirmed.

## Confirmed aliases (verified live against real agent output today)

| Ellis field key | Creao canonical name(s) | Confirmed via |
|---|---|---|
| `lpr_since` | `date_lpr`, `date_became_lpr` | case_manager run, docket_clerk run |
| `dob` | `date_of_birth` | case_manager run |
| `a_number` | `alien_number` | qa_reviewer run |
| `name.given` + `name.family` | `legal_name` (combined) | qa_reviewer run |
| `sex` | `gender` | qa_reviewer run |
| `marital.status` | `marital_status` | qa_reviewer run |

All of the above are now wired into `_to_case_bundle()` in `backends.py` and proven working.

## One important finding: there are no real missing fields, only more naming mismatches

qa_reviewer's first live run reported `marital_status`, `ssn`, `current_address`, `gender`,
`residences`, `trips`, and `employment_history` as "missing required fields" on `c_maria`. I checked
`fields.yaml` directly: **every one of these already exists as a real Ellis field** (`marital.status`,
`ssn`, `contact.phone`, `sex`, `addresses`, `trips`, `employment`) — they were either just unanswered by
this particular demo case, or (for `gender`/`residences`) yet another naming mismatch, not an actual
schema gap. **Nobody needs to add new columns to Supabase for this.** The `sex`→`gender` and
`marital.status`→`marital_status` aliases above cover two of them; the rest were just unanswered data.

## Known remaining gap (not yet fixed, flagging honestly)

`addresses` (Ellis's address-history list) and `trips` aren't flat single-value facts the way
`lpr_since` or `dob` are — they're list sections, and the bundle format Creao's engines expect has
`trips`/`residences` as their own top-level arrays (not items inside `facts`). `_to_case_bundle()`
doesn't build those sections yet. This is next on the list, not done — whoever picks up the Creao
integration next should build the list-to-array mapping for `trips` and `addresses`→`residences`
before relying on those sections in agent output.

## What the Creao-integration side should NOT do

Don't build any new Supabase-aware code assuming a particular schema shape. Everything in
`backends.py` reads through `build_context()`, which is the existing abstraction boundary — it already
doesn't care what database is underneath. Keep it that way.
