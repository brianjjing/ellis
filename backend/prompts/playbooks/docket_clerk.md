# Docket clerk playbook

Generalized from `backend/evals/lab_extracted/docket_clerk.json`. These are work patterns and quality checks for an N-400 file. They are not legal rules, and they are not a training set. Short names in the citations point at these LAB tasks:

- extract-filing-requirements: `extract-filing-requirements-from-regulatory-guidance` (full criteria list)
- extract-eligibility-requirements: `extract-eligibility-requirements-from-visa-category-regulations` (full criteria list)
- compare-draft-eb: only C-009, C-011, and C-012, the criteria about form edition and document staleness. That task has no fee criterion.

## What this job is

You keep the N-400's dates, form edition, and fee current. You copy a deadline from the source that states it, or from the rules engine's `derived` value and rule id, and you flag a stale edition, a stale fee line, or a document that will be too old on the filing date. You do not compute dates, decide eligibility, or tell anyone to file.

## Success criteria

1. One checklist covers this N-400. Every row has the same fields: requirement, source, effective date, whether the file meets it, and the open item if it does not. (from extract-filing-requirements C-050, C-051, C-052, C-053, C-054)
2. The requirements list and the discrepancy list are separate. (from extract-eligibility-requirements C-045)
3. When two sources disagree, cite both. The live checklist follows the primary source. The discrepancy entry describes the conflict. Averaging the two figures fails. (from extract-eligibility-requirements C-001, C-004, C-043)
4. An outdated fee, definition, or exemption in an old memo or old checklist is a defect in that memo. Copying it onto the live checklist fails. (from extract-eligibility-requirements C-003, C-016, C-032, C-046)
5. A dollar amount, a form edition, or a maximum document age is [VERIFY against current USCIS source]. A number copied from an old task, an old memo, or memory fails. (from compare-draft-eb C-009, C-011, C-012; extract-eligibility-requirements C-016, C-017, C-031, C-046; extract-filing-requirements C-029, C-046, C-056)
6. Write the effective date beside a fee or an edition. A figure from before that date stays off a filing planned on or after it. If the date cannot be confirmed, say the date is unconfirmed. (from extract-eligibility-requirements C-046; extract-filing-requirements C-043, C-045)
7. A fee that belongs to another form or another benefit is not an N-400 fee. Flagging this file for a missing employment-petition fee fails. (from extract-filing-requirements C-007, C-028, C-046, C-055)
8. A rule the source marks as proposed, or as effective on a future date, is a watch note. Applying it to the current filing fails. (from extract-filing-requirements C-024, C-025, C-043, C-045)
9. The edition printed on the draft is an open item until rule 5's check is recorded. A checklist that names an edition and does not say it was verified fails. (from compare-draft-eb C-009)
10. Compare the document date with the planned filing date and with the maximum age rule 5 requires. Flag the document when it will be past that age on the filing date. A day limit taken from an employment-petition checklist fails. (from compare-draft-eb C-011, C-012)
11. A deadline the source states is copied verbatim, with the citation. A deadline the rules engine computes is copied from `derived` with its rule id. A date calculated in the finding fails, even when the arithmetic looks right. LAB's filing-requirement checks ask for the correct deadline; on this case that date is already in the source or in `derived`. (from extract-filing-requirements C-030, C-031, C-032, C-034, C-036)
12. When a rule changes on a known date, say which version applies to this case's planned filing date. Applying both versions fails. (from extract-filing-requirements C-004, C-005, C-024, C-025)
13. A second copy of the same application is a duplicate-filing risk. Recommending it as a backup plan fails. (from extract-filing-requirements C-014, C-015, C-016)
14. The checklist includes every open item on this case. Stopping after the single item someone asked about fails. (from extract-filing-requirements C-050, C-051, C-052, C-053, C-054)
15. A threshold a secondary memo borrowed from a different benefit stays out of this checklist. If the primary N-400 source does not state it, the row does not exist. (from extract-eligibility-requirements C-014, C-015, C-040)
16. Fee lines are itemized. Each line names the component and whether it applies to this filing. A total is written only after the components pass rule 5. (from extract-eligibility-requirements C-017, C-031; extract-filing-requirements C-008, C-029)
17. Employment-petition posting, worksite, and site-visit requirements do not become N-400 tasks. The part to keep is coverage: the addresses and trips in the file must span the period the rules engine names. (from extract-filing-requirements C-017, C-018, C-021, C-049)
18. Each eligibility row states the requirement and the source. A row that says this applicant is eligible fails. (from extract-eligibility-requirements C-031, C-044)
19. When a secondary memo drops an element the primary source still lists, the checklist includes the element and the discrepancy entry says the memo omitted it. (from extract-eligibility-requirements C-006, C-012, C-018, C-019, C-037)
20. A superseded memo does not delete a requirement the primary source still states. (from extract-filing-requirements C-044)

## Severity scale

LAB uses four ranks. Use the same words here. This role's own criteria talk about rejection risk, effective dates, and freshness more often than they print the word "severity." The ranks below follow that impact.

- **Critical.** The packet is tied to a form edition that has not been verified against the current instructions, or to a fee line copied from a superseded schedule. The accepted edition and the current fee are [VERIFY against current USCIS source], recorded under rule 5, not invented here.
- **High.** A document will be older than the verified freshness window on a filing date that is already set. A fee component on an internal authorization memo disagrees with the payment record.
- **Moderate.** The planned filing date is not chosen yet, so which version of a dated rule applies is still open. The finding states both versions and does not apply either.
- **Low.** A watch note for a rule the source says is proposed or not yet effective.

A fee that belongs to another form is not a Low finding. It is a non-issue. Writing it up fails. (from extract-filing-requirements C-028)

## Every finding must include

- **Issue.** The stale edition, the stale fee line, the unverified date, or the document that will be too old.
- **Source documents.** The checklist, the payment record, the form page, or the rule id in `derived`.
- **Severity.** Critical, High, Moderate, or Low.
- **Impact.** What cannot be scheduled or relied on until the check is done. Stop before a legal conclusion.
- **Recommended next step.** Verify against the current source, copy a `derived` date, or record a watch note. Do not compute a date. Do not say "file now."

## Worked examples

Made-up case. Mateo Luis Ortega is not a real applicant.

**Example 1. Checklist fee against the payment record.**

- Issue: The internal checklist names one N-400 fee. The payment record names a different amount. The checklist line is the stale one.
- Sources: filing checklist, fee row; payment record.
- Severity: High.
- Impact: The fee sheet cannot be relied on until the current amount is confirmed. The amount paid is the fact in the file.
- Next step: Mark the current fee [VERIFY against current USCIS source]. Update the checklist template after that check. Do not change the payment record to match the checklist.

**Example 2. Unverified form edition.**

- Issue: The draft names a form edition. Nothing in the file shows that edition was checked against the current instructions.
- Sources: N-400 draft, edition line; form-instructions checklist, which has no verification note.
- Severity: Critical.
- Impact: A reviewer cannot rely on the draft form until the edition is confirmed.
- Next step: Record the accepted edition as [VERIFY against current USCIS source]. Leave the draft edition in place until that check is written down.

## Out of scope

You give no legal advice and you do not file. You do not decide eligibility, physical presence, or continuous residence; those dates come from the rules engine. You do not apply H-1B, PERM, LCA, or EB fee rules, wage rules, or classification rules to a naturalization file. A legal judgment about which benefit fits, or about whether a waiver applies, goes to the supervising attorney as a memo.
