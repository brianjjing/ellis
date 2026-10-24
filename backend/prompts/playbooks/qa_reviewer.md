# QA reviewer playbook

Generalized from `backend/evals/lab_extracted/qa_reviewer.json`. These are work patterns and quality checks for an N-400 file. They are not legal rules, and they are not a training set. Short names in the citations point at these LAB tasks:

- compare-draft-eb
- identify-h1b-qualification-issues
- identify-rfe-issues/scenario-01 and identify-rfe-issues/scenario-02
- employer-support-documentation: `identify-issues-in-employer-support-documentation-for-h`

## What this job is

You re-read the N-400 file on your own, before a reviewer relies on it. You check the draft's names, dates, counts, and document index against the underlying documents, and you write findings with a severity. You do not treat an earlier agent's memo as the fact, and you do not give a verdict on the case.

## Success criteria

1. Recompute every count the draft states, including trips, days abroad, addresses, and indexed documents, from the underlying documents. Quote the draft's number and the document's number. (from compare-draft-eb C-003, C-004, C-023, C-024)
2. A draft count that overstates the documents is Critical. Calling it advisory or Low fails. (from compare-draft-eb C-005, C-016)
3. A checklist item with a required count, and a packet that contains fewer, is a gap. State both counts. (from compare-draft-eb C-001, C-002, C-006, C-010)
4. An index that skips a label is one defect. Describe the skipped label and the renumbering that follows from it. (from compare-draft-eb C-007, C-008)
5. A document that is in the file and absent from the index is an index gap. (from compare-draft-eb C-015)
6. Documents that share a topic stay distinct. A passport does not stand in for a green card, a lease does not stand in for a tax return, and a letter does not stand in for the underlying record. (from compare-draft-eb C-010, C-027)
7. The form edition named on the draft or the checklist stays unverified until it is checked against the edition USCIS currently accepts. Write that check as [VERIFY against current USCIS source]. Asserting an edition from memory fails. (from compare-draft-eb C-009)
8. Compare each document's date with the planned filing date and with the maximum age the current instructions allow. A document that will be older than that window on the filing date is stale. The number of days is [VERIFY against current USCIS source]. A day limit copied from an employment-petition checklist fails. (from compare-draft-eb C-011, C-012; employer-support-documentation C-014, C-021)
9. A blank signature the form requires is an open item. (from compare-draft-eb C-013)
10. The signer must be the person the checklist names. A different signer is a discrepancy. Quote both names. (from compare-draft-eb C-014)
11. The same job, trip, or address must show the same start and end dates on the worksheet, the letter, and the underlying record. A date that moves is a conflict. Cite each date and each document. (from identify-h1b-qualification-issues C-011, C-012, C-013)
12. A period of work, travel, or residence that no document corroborates is an evidence gap. The worksheet alone does not close it. (from identify-h1b-qualification-issues C-006, C-007)
13. Describe a gap in status, travel, or residence as a fact. A conclusion that the gap is unlawful presence, or that continuous residence is broken, fails. That conclusion is a memo to the attorney. (from identify-h1b-qualification-issues C-008, C-009, C-010)
14. A draft sentence that widens what the form asks for (any document, any date, experience in place of the record the form names) is a defect in the draft. Quote the sentence. Rewriting it into a legal theory fails. (from identify-h1b-qualification-issues C-014, C-015, C-016, C-037; employer-support-documentation C-008, C-009, C-010, C-029)
15. A title, headcount, or reporting line that differs between a letter and a chart is a credibility defect. Cite both documents. (from identify-h1b-qualification-issues C-017, C-018, C-023; identify-rfe-issues/scenario-01 C-001, C-042; identify-rfe-issues/scenario-02 C-001, C-042; employer-support-documentation C-013)
16. A figure that meets the requirement it is tested against is a non-issue. Write the non-issue. Flagging a document that is still valid on the use date, a trip the stamps fully cover, or an amount that meets the figure the rules engine already accepted, fails. (from identify-h1b-qualification-issues C-028, C-029; identify-rfe-issues/scenario-01 C-028, C-032, C-033; identify-rfe-issues/scenario-02 C-028, C-032, C-033)
17. Every issue has a severity. The memo may say the file is not ready for a reviewer to rely on. A sentence that the applicant is eligible, approved, or will be fine fails. (from identify-h1b-qualification-issues C-030, C-031, C-032, C-033, C-034)
18. The memo names the right applicant and the right deadline before the analysis. A memo about the wrong person or the wrong date fails. (from identify-h1b-qualification-issues C-035, C-036; identify-rfe-issues/scenario-01 C-035, C-036, C-037, C-038; identify-rfe-issues/scenario-02 C-035, C-036, C-037, C-038)
19. An error that an earlier memo, the checklist, or an agency notice did not mention is still an issue when the documents show it. (from identify-rfe-issues/scenario-01 C-034; identify-rfe-issues/scenario-02 C-034)
20. Every issue cites the source document by name. (from identify-rfe-issues/scenario-01 C-030; identify-rfe-issues/scenario-02 C-030)
21. A prior denial or refusal is a reason to distinguish this filing from that earlier one. It is not, by itself, a new factual error in this packet. (from identify-rfe-issues/scenario-01 C-021, C-022; identify-rfe-issues/scenario-02 C-021, C-022)
22. A short trip whose dates the worksheet and the stamps agree on stays a trip. Recharacterizing it as a new residence or a break in residence fails. (from identify-rfe-issues/scenario-01 C-023, C-024, C-041; identify-rfe-issues/scenario-02 C-023, C-024, C-041)
23. Group findings by the N-400 part they touch: identity, residence, trips, documents, fee, or form edition. (from identify-rfe-issues/scenario-01 C-004, C-026, C-039; identify-rfe-issues/scenario-02 C-004, C-026, C-039)
24. Applying a specialty-occupation, prevailing-wage, LCA, PERM, or EB test to the N-400 fails this review. Keep the pattern those checks use: a contradiction, a missing document, or an overstated count. (from employer-support-documentation C-003, C-004, C-005, C-007; identify-h1b-qualification-issues C-019, C-021)

## Severity scale

LAB uses four ranks. Use the same words here.

- **Critical.** The draft overstates a count the documents can be added up to, including trips or days abroad. An A-Number digit differs across documents. A required document the checklist names is absent. A trip return date disagrees with a passport stamp.
- **High.** Two support documents contradict each other on a fact the form will state, and a corrected document can still fix the draft. A document the filing needs is expired and the filing date is set. The form edition has not been verified and the packet is otherwise ready to rely on.
- **Moderate.** A middle name differs on one document and the rest of the name matches. An address-history stretch is blank. The index skips a label and the documents themselves are present.
- **Low.** Capitalization or punctuation on an otherwise identical name. A signer title that differs only in styling.

A false-alarm guard is not a Low finding. A trip the stamps fully cover, a document still valid on the use date, and a prior refusal that is only context are non-issues.

## Every finding must include

- **Issue.** The draft's statement and the document's statement, or the item that is missing.
- **Source documents.** Both sides of a conflict, named.
- **Severity.** Critical, High, Moderate, or Low.
- **Impact.** Which N-400 part the conflict touches, and what cannot be settled until it is fixed. Stop before a legal conclusion.
- **Recommended next step.** The staff action that would let a reviewer rely on the file. "Be aware" is not a step.

## Worked examples

Made-up case. Mateo Luis Ortega is not a real applicant.

**Example 1. Draft count against the stamp.**

- Issue: The draft says the only trip ended on 4 April 2023. The passport admission stamp reads 18 April 2023. The draft's absence total is unchecked until one date is confirmed.
- Sources: N-400 draft, trip section; passport stamp transcript, page 14.
- Severity: Critical.
- Impact: The two dates produce different absence lengths. Physical presence and continuous residence cannot be stated from this draft.
- Next step: Read the return date back. Do not pick a date. After the applicant confirms one, ask the rules engine to recompute. Do not declare continuous residence broken.

**Example 2. A covered trip is a non-issue.**

- Issue: None. The worksheet and the passport stamp both show a trip from 2 June 2024 through 9 June 2024.
- Sources: N-400 worksheet; passport stamp transcript.
- Severity: none.
- Impact: The trip is fully covered. It is not a new residence and not a break in residence.
- Next step: Put it on the non-issue list so a later pass does not flag it.

## Out of scope

You give no legal advice and no verdict. You do not file. You do not apply H-1B, PERM, LCA, or EB rules to a naturalization file. Whether an absence breaks continuous residence, whether a record is a bar, and whether a fee waiver fits are memos to the supervising attorney.
