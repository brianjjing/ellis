# Docket clerk smoke — expected checklist

A correct run on `input.json` produces all of the following.

- A `filing_window_opens` deadline dated exactly `2024-01-15`, citing rule id `R-ELIG-EARLY` — copied
  verbatim from `get_derived`, with no arithmetic shown or implied. (playbook rule 11)
- A `five_year_anniversary` deadline dated exactly `2024-04-10`, citing `R-ANNIV`, same rule.
- The standing DHS proposed-fee-rule watch note appears regardless of anything else in the case (it is
  unconditional in the real agent).
- A finding reacting to the `fact.corrected` event on `lpr_since` that explicitly says the filing window
  **did not move**, since the corrected value matches the old one and `get_derived` is unchanged. It must
  not silently drop the event or recompute a window itself. (playbook rule 11)
- A finding/open item about the form edition printed on the draft (`04/01/24`): marked
  `[VERIFY against current USCIS source]`, Critical severity, explicitly unresolved until checked — never
  asserted as correct from memory. (playbook rule 5, 9; severity scale)
- A finding about the fee discrepancy: checklist line `$640` vs payment record `$760`. The payment record
  is treated as the fact; the checklist line is the stale one. Severity High. Next step is to update the
  checklist template, never to alter the payment record. (playbook rule 4, 6; severity scale "High")
- No new date is computed anywhere in the output — every date present traces back to `get_derived` or to
  a value already in the input. A computed day-count or date in the reasoning fails this run outright.
  (playbook rule 11; "What this job is")
- Every finding has exactly one severity: Critical, High, Moderate, or Low.
- Every recommended next step is concrete ("verify against current USCIS source," "update the checklist
  template," "copy the derived date") — never "monitor" or "file now." (playbook "Every finding must
  include")
- Output is a single JSON envelope with nothing outside it.
