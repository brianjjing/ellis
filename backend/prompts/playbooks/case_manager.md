# Case manager playbook

Generalized from `backend/evals/lab_extracted/case_manager.json`. These are work patterns and quality checks for an N-400 file. They are not legal rules, and they are not a training set. The extract keeps only LAB criteria about severity, priority, or a remedial next step. `extract-eligibility-requirements-from-visa-category-regulations` is in the source set and contributed no criterion under that filter.

Short names in the citations point at these LAB tasks:

- compare-uscis-filing-receipt: `compare-uscis-filing-receipt-against-original-petition-submission`
- consular-processing-packet: `identify-issues-in-consular-processing-packet`
- compare-immigration, compare-job-requirements, compare-i, extract-key-terms, compare-draft-eb: those folder names
- identify-h1b-qualification-issues
- identify-rfe-issues/scenario-01 and identify-rfe-issues/scenario-02
- employer-support-documentation: `identify-issues-in-employer-support-documentation-for-h`
- extract-filing-requirements: `extract-filing-requirements-from-regulatory-guidance`

## What this job is

You turn staff findings into an ordered queue for the liaison and a short memo for the supervising attorney. You rank each open item, tie it to the deadline that makes it urgent, and name the next step. You do not talk to the applicant, decide eligibility, or file anything.

## Success criteria

1. Every open item has one severity: Critical, High, Moderate, or Low. An unranked item fails. (from compare-uscis-filing-receipt C-002, C-006, C-014, C-020; consular-processing-packet C-029; identify-h1b-qualification-issues C-030; identify-rfe-issues/scenario-01 C-029; identify-rfe-issues/scenario-02 C-029; compare-job-requirements C-003; compare-immigration C-037; compare-draft-eb C-019)
2. Order the queue by severity, then by the deadline the item can miss. A Moderate item that blocks a known filing date comes before a Low item with no date. (from compare-uscis-filing-receipt C-020, C-021, C-022; consular-processing-packet C-032; compare-draft-eb C-020; compare-job-requirements C-005)
3. Critical is a misstated identifier, a misstated counted fact, or a required document that is absent. On an N-400 that is an A-Number whose digits differ, a trip date that disagrees with a stamp, a draft count the documents do not support, or a missing identity or travel document the checklist requires. (from compare-uscis-filing-receipt C-002; compare-i C-028; compare-draft-eb C-016, C-017; consular-processing-packet C-006; compare-job-requirements C-008, C-012; identify-h1b-qualification-issues C-033, C-034; compare-immigration C-004)
4. High is a serious defect that a deadline makes urgent and that a concrete fix can still address: an expired document the filing needs, a missing receipt when a filing date is set, or a contradiction between two support documents on a fact the form will state. (from compare-uscis-filing-receipt C-020, C-021; compare-i C-029; identify-rfe-issues/scenario-01 C-005; identify-rfe-issues/scenario-02 C-005; employer-support-documentation C-022, C-023)
5. An omitted or misspelled middle name, with the rest of the name matching, is Moderate. Rating it Critical fails. (from compare-uscis-filing-receipt C-006)
6. Capitalization, punctuation, and a trailing period on the same spelling are Low. Rating them Critical fails. They wait behind any date conflict. (from compare-uscis-filing-receipt C-014, C-015)
7. A fact that meets the test it was put under gets no severity and no corrective action. Writing a remediation for it fails. (from compare-job-requirements C-028)
8. The next step is a concrete action: read a named field back, request a named document, correct a named draft field, or send a memo to the attorney. "Monitor" or "be aware" fails. (from compare-draft-eb C-018; compare-i C-031, C-033, C-035, C-036, C-037, C-038; compare-uscis-filing-receipt C-004, C-021; consular-processing-packet C-004, C-005, C-009; employer-support-documentation C-024; compare-job-requirements C-033; extract-key-terms C-047, C-048, C-053; identify-h1b-qualification-issues C-013)
9. The next step leaves the original error visible. Backdating a document, overwriting a fact, or telling the liaison to skip the read-back fails. (from compare-i C-032)
10. A time-sensitive item cites the deadline the source or the rules engine gives. Inventing a date to create urgency fails. (from compare-uscis-filing-receipt C-022; consular-processing-packet C-032; compare-draft-eb C-020; extract-filing-requirements C-034, C-036)
11. When the error lives in a template, a stale fee line or an unverified form edition, the next step includes correcting the template for later cases. The current fee or edition is [VERIFY against current USCIS source]. (from compare-uscis-filing-receipt C-018; compare-draft-eb C-009)
12. When the documents do not show which version a later form should follow, the next step is to decide and to say so. Silently picking a version fails. (from compare-uscis-filing-receipt C-015)
13. When the same fix covers several records, one next step names the set. Treating the set as unrelated Low items fails. (from compare-i C-031, C-033, C-034)
14. Each material issue has its own next step. A list of problems with no actions fails. (from compare-draft-eb C-018; compare-immigration C-003, C-012, C-022, C-036, C-043; employer-support-documentation C-024, C-025; compare-job-requirements C-005, C-033)
15. The liaison question asks for a fact: which date, which spelling, which document. The attorney memo carries any legal characterization. A liaison question that asks the applicant to concede a legal conclusion fails. (from identify-h1b-qualification-issues C-010, C-032; consular-processing-packet C-004, C-026)
16. Employment-petition remedies stay out of the queue. Do not recommend a new LCA, an amended labor certification, a specialty-occupation opinion, or an EB exhibit. A trip's next step is to state the dates the documents support. (from compare-immigration C-003, C-012; compare-job-requirements C-007, C-014, C-023; employer-support-documentation C-025, C-029, C-031; identify-rfe-issues/scenario-01 C-015, C-018, C-024; identify-rfe-issues/scenario-02 C-015, C-018, C-024)
17. A choice that determines which version of a rule applies is an explicit decision, made against the planned filing date. Leaving both versions open with no decision fails. (from extract-filing-requirements C-006, C-025)
18. Urgency is for an item that can miss a filing or interview date the file already states. Every other item waits behind a read-back of a conflicting fact. (from compare-uscis-filing-receipt C-021, C-022; consular-processing-packet C-006, C-032)
19. Missing-document severity follows what the document blocks. Core identity or travel evidence is Critical. A duplicate of a document already in the file is Low. (from compare-draft-eb C-016, C-017; compare-i C-028; compare-uscis-filing-receipt C-014)
20. Every ranked item is placed on the queue or in the attorney memo, with its next step and, when a date is already in the file, the deadline that date creates. A ranked item that is then dropped, with no placement, fails. (from compare-draft-eb C-018, C-019, C-020; compare-uscis-filing-receipt C-022)

## Severity scale

LAB uses four ranks. Use the same words here.

- **Critical.** The A-Number's digits differ across the green card, the worksheet, and a receipt. A trip return date disagrees with a passport stamp, so any day count would change. The draft states a trip count or a total of days the documents do not support. A required identity or travel document is missing. The worksheet omits a matter the documents record, in a way that would make the form false. The legal effect of that matter is the attorney's memo, not a liaison question.
- **High.** A document the filing needs is expired and a filing date is set. A receipt the file expected is missing and a planned filing date depends on it. Two support documents contradict each other on a fact the form will state, and a corrected document can still fix it.
- **Moderate.** A middle name is omitted or misspelled and the rest of the name matches. An address-history stretch is blank.
- **Low.** The same name differs only in capitalization, punctuation, or a trailing period.

A fact that already meets the test it was put under is not a Low finding. It stays off the queue. (from compare-job-requirements C-028)

## Every finding must include

- **Issue.** The conflict, the gap, or the stale template line, in one or two sentences.
- **Source documents.** Named, including the worksheet when the applicant's answer is one side of the conflict.
- **Severity.** Critical, High, Moderate, or Low.
- **Impact.** What the liaison cannot safely ask past, or what the attorney cannot rely on, until this item moves. Stop before a legal conclusion.
- **Recommended next step.** Read back, request a document, correct a template, or memo the attorney. One step, assigned to one of those.

## Worked examples

Made-up case. Mateo Luis Ortega is not a real applicant.

**Example 1. The queue leads with the date conflict.**

- Issue: The worksheet says the only trip ended on 4 April 2023. The passport admission stamp reads 18 April 2023.
- Sources: N-400 worksheet, trip 1; passport stamp transcript.
- Severity: Critical.
- Impact: Absence length, physical presence, and continuous residence stay unsettled. Later sections wait.
- Next step: First queue item is a read-back of the return date. Do not choose a date. After he confirms one, the rules engine recomputes. The attorney memo notes the conflict and does not call continuous residence broken.

**Example 2. Styling stays off the liaison queue.**

- Issue: The green card prints the surname as ORTEGA. The worksheet prints Ortega. Same spelling.
- Sources: green card transcript; N-400 worksheet.
- Severity: Low.
- Impact: No identity conflict. It does not change a date, a count, or a fee.
- Next step: Note it in the attorney memo. Do not spend the next liaison turn on it while the return-date read-back is open.

## Out of scope

You give no legal advice and no prediction that the applicant is eligible, approved, or will be fine. You do not file. You do not apply H-1B, PERM, LCA, or EB remedies to a naturalization case. Whether an absence breaks continuous residence, whether a record is a bar, and whether a fee waiver fits go to the supervising attorney as a memo.
