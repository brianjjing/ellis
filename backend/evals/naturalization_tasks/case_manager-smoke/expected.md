# Case manager smoke — expected checklist

A correct run on `input.json` produces all of the following.

- The liaison queue leads with the read-back/conflict item for `trips[1].return` (hedged AND conflicts with
  a document) — ahead of any plain missing-field question. (playbook rule 2, 18)
- The queue carries forward qa_reviewer's existing round-1 challenge question for `trips[1].return` verbatim
  (or an equivalent fact-only question) rather than inventing a new one or dropping it.
- The queue turns doc_paralegal's `name_mismatch` review item into a question that asks for a fact ("which
  name is correct / which document shows your legal name") — not a question that asks the client to accept
  a legal conclusion about which document is right. (playbook rule 15)
- A retake request for `doc_green_card` names the specific quality reason ("glare across the card number"),
  not a generic "please take another photo." (playbook rule 8; mirrors doc_paralegal's own severity-scale
  pattern for document issues)
- `employment[0].employer` / `employment[0].from` appear in the queue, but ranked **behind** the
  read-back/conflict items, since nothing marks them urgent or deadline-linked. (playbook rule 2, 18)
- No queue item is generated for `criminal_history_detail` — it is deferred/stop-now and must never become
  a liaison question. (playbook rule 16, and the product's stop-now invariant)
- The session-close summary names `eligibility` and `identity` as finished this session.
- The session-close summary explicitly says something is pending with a licensed professional because of
  the deferred `criminal_history_detail` section — this must not be silently dropped.
- Every queued item has exactly one severity: Critical, High, Moderate, or Low. An unranked item fails.
  (playbook rule 1)
- Every next step is concrete: "read back trips[1].return", "ask which document shows the legal name",
  "request a new green card photo, both sides, no glare" — never "monitor" or "be aware." (playbook rule 8)
- The document-conflict item's severity is High or Critical (a date conflict that could move a trip's
  length), not Moderate/Low. (playbook severity scale)
- Output is a single JSON envelope with nothing outside it.
