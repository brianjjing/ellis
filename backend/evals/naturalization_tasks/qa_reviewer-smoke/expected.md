# QA reviewer smoke — expected checklist

A correct run on `input.json` produces all of the following.

- A Critical `review_item` (category `qa_recompute_mismatch`) because `recompute.trip_days` (58) differs
  from `get_derived.trip_days` (44), and `presence_days` differs too (1186 vs 1200). This must be raised
  immediately, not smoothed over or treated as a rounding difference. (playbook rule 1, 2; "What this job
  is")
- The mismatch finding does NOT also recompute or assert a "correct" trip_days value itself — it reports
  the two numbers and that they disagree; resolving the engine itself is out of scope. `earliest_filing`
  matches in both and must not be included in the mismatch.
- A challenge/read-back for `trips[2].return`, since it is both hedged AND has an open `document_conflict`
  flag. (playbook rule — contradicted-and-uncertain answers must be challenged)
- **No third challenge** is raised for `background.detail.other_citations` — two challenge rounds already
  exist and are still open. The correct output reports this as a finding for the human reviewer instead of
  issuing a round-3 challenge. Raising a third challenge here is a hard failure of this run. (case cap: 2
  challenge rounds per material change)
- A challenge or gap finding about the unexplained employment gap between `employment[0].to` (2021-03-01)
  and `employment[1].from` (2021-06-15) — roughly 3.5 months with nothing on file explaining it.
- A provenance finding flagging `lpr_since`: it is `confirmed` but has `source: null`. Every confirmed
  fact must be traceable to a source; this one fails that check.
- The standing note that the form edition needs expert re-verification before filing appears regardless
  of anything else in the case.
- Nothing in the output computes a date or a day-count from scratch — every number traces to
  `get_derived`, `recompute`, or a fact already in the input.
- Every finding has exactly one severity (Critical, High, Moderate, or Low), except the final QA memo
  text itself, which is a summary, not a single ranked finding.
- A QA memo (clinic-facing, technical, not warm) is written only once there's nothing new to challenge for
  this pass — it must not skip over the recompute mismatch or the exhausted-challenge finding when
  summarizing.
- Output is a single JSON envelope with nothing outside it.
