# External tooling for the four Creao agents — brainstorm log

Running list from brainstorming, not an implementation plan. Nothing here is built yet.

## Fixed — found while brainstorming, not a tool

`_to_case_bundle()` never sent the case's actual selected language to any agent. Root cause turned out
deeper than the bundle: `build_context()` (`ellis/agents/context.py`) on this `creao` branch never
computed `language` at all -- `ctx["language"]` raised `KeyError`, and every `ctx.get("language", "es")`
call site was silently swallowing that into a Spanish default. (The `context.py` fix for this already
existed on a different branch, `cartesia-fix`, from earlier the same day -- just never made it here.)

Fixed 2026-10-24: `context.py` now sets `"language": cs.case_lang(case)`; `_to_case_bundle()` sends it as
`client_language` both at the top level and inside `case` (the agents' own documented bundle shapes
disagree on which, so both are covered). Verified: a case mutated to `en-US` now correctly produces
`client_language: "en"` in the bundle; the real `c_maria` (es-MX) still correctly produces `"es"`, no
regression. 60/60 tests still pass.

Known follow-up, not done: this only fixes what the *Creao* agents see. `ellis/agents/skeleton.py`
(the deterministic fallback backend) may have the same class of gap on this branch if its own earlier
language-awareness fixes also live only on `cartesia-fix` -- not checked, flagging so it isn't assumed
fixed by extension.

## Pinned for later

- **USCIS fee schedule / current form edition lookup.** All three of paralegal, docket_clerk and
  qa_reviewer independently flag `[VERIFY against current USCIS source]` in their own rubrics as an
  unresolved gap, repeatedly. Highest-leverage item on this whole list, deliberately saved for last.

## Queued to build (agreed, not started)

1. **Green card / visa category code lookup** (doc_paralegal). Resolves codes like `IR6` ("spouse of a
   US citizen") into their meaning, so a flagged mismatch (e.g. category vs. `married_to_us_citizen`)
   can be confirmed automatically instead of just raised as a vague question. Static reference table.

2. **A-number / receipt-number format validator** (qa_reviewer). Checks the known, checkable formats
   (digit counts, service-center prefixes: MSC/LIN/WAC/EAC) so a transposed digit or malformed number is
   caught with certainty rather than by the model eyeballing it. Pure logic, no external data needed.

3. **N-400 field-schema validator** (case_manager). Validates `fill_n400`'s output against the real
   current N-400 field formats/character limits before a human reviewer ever sees it.

4. **Document parser + extraction tool** (doc_paralegal). Note for when we scope this: Ellis already
   has its own extraction pipeline (`ellis/extraction/`), and right now paralegal only ever sees
   *already-extracted* structured data via the inline bundle (`_to_case_bundle()`'s
   `extraction`/`extracted_text` field) — it never touches a raw document today. Worth deciding, when we
   get to it, whether this tool is (a) genuinely new/better extraction paralegal calls directly, or (b) a
   way to let paralegal re-verify/re-run extraction live on a document it's unsure about, rather than
   duplicating what already exists.

## More ideas from this round (not yet agreed — for discussion)

- **Bilingual document cross-check tool** (doc_paralegal). Its own rubric already has a rule: compare
  every name/date/number between an original document and its certified English translation. Right now
  that comparison is just the model reading two blocks of text; a structured bilingual alignment tool
  could make it far more precise than eyeballing. Broadened below (not Spanish-English specific) since
  Ellis's language support is meant to extend past just those two.

### Multi-language tooling (prompted by: Cartesia's language picker should extend to documentation)

- **Document language detection tool** (doc_paralegal). Detects what language a document is actually
  written in, instead of trusting its label. Catches a mismatch -- applicant says "my birth certificate"
  but the extracted text isn't in the language expected -- as a mechanical check, not a guess.

- **Certified-translation completeness checker** (doc_paralegal). USCIS requires a certified English
  translation for any foreign-language document submitted with the N-400, with a specific certification
  statement format. A tool that checks whether a non-English document in the case file has a matching
  certified translation attached -- and flags it if the certification statement itself looks malformed or
  missing -- is a real, checkable USCIS requirement, not a nice-to-have. Directly extends the bilingual
  cross-check tool above: detect the language first, then confirm the translation obligation is met.

- **Applicant-language-consistency checker** (case_manager). Given case_manager is the one agent writing
  live, client-facing text (`set_question_queue`), a check that every string it generates actually matches
  the applicant's selected language -- not assumed from habit -- directly closes the same class of gap as
  the bundle bug noted above, just enforced going forward instead of relying on the bundle always being
  correct. Worth building once the bundle fix lands, as a belt-and-suspenders check, not a replacement
  for it.

- **Federal holiday / business-day calendar** (shared: doc_paralegal + docket_clerk). Paralegal's lockbox
  -timing logic and docket_clerk's overdue/due-soon logic both implicitly need to know what counts as a
  business day. Right now that's just the model's own knowledge, which won't reliably hold for future
  years. An authoritative calendar tool would make both bulletproof.

- **USCIS field-office locator** (docket_clerk). Maps an address to the applicant's actual jurisdiction
  /field office, so processing-time and deadline guidance can be office-specific instead of a national
  average.

- **Cross-document structured diff tool** (qa_reviewer). A mechanical field-by-field comparison between
  two documents' extracted JSON, rather than relying on the model's own prose comparison to catch a
  subtle mismatch. Fits qa_reviewer's "don't trust anyone, re-verify independently" mandate directly.

- Considered and set aside: a civics/English exemption-rule lookup for case_manager — this already exists
  in Ellis's own rules engine (the 50/20, 55/15 exemptions), so an external tool here would be redundant,
  not additive.
