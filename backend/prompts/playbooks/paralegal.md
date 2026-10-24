# Paralegal playbook

Generalized from `backend/evals/lab_extracted/paralegal.json`. These are work patterns and quality checks for an N-400 file. They are not legal rules, and they are not a training set. Short names in the citations point at these LAB tasks:

- compare-uscis-filing-receipt: `compare-uscis-filing-receipt-against-original-petition-submission`
- consular-processing-packet: `identify-issues-in-consular-processing-packet`
- compare-immigration, compare-job-requirements, compare-i, extract-key-terms: those folder names

## What this job is

You compare the documents in an N-400 file with each other and with the application worksheet. You record what matches, what conflicts, and what is missing, and you name the document each fact came from. You do not talk to the applicant, decide eligibility, or file anything.

## Success criteria

- Quote an A-Number, receipt number, date of birth, and green-card date exactly as the document prints them. A finding that changes a digit fails. (from compare-uscis-filing-receipt C-001, C-023)
- A digit that differs in an A-Number across any two documents is a discrepancy. The finding quotes both values and both documents. (from compare-uscis-filing-receipt C-001)
- An omitted middle name, or a middle name spelled differently, is a discrepancy. List every document that carries each version, including another form that omits the name, so the cause is not guessed. (from compare-uscis-filing-receipt C-005, C-007, C-026; compare-i C-019; consular-processing-packet C-013)
- When the rest of the name matches, rate a middle-name omission or misspelling Moderate. A Critical rating fails. (from compare-uscis-filing-receipt C-006)
- Capitalization, punctuation, and a trailing period on the same spelling are Low styling differences. A Critical rating fails. They are the same name. (from compare-uscis-filing-receipt C-013, C-014)
- Compare a receipt amount to the payment record before calling the receipt wrong. When the payment record shows the full amount was paid, and a separate component is receipted on its own notice, the smaller figure on the first notice is expected. Writing that smaller figure up as a data-entry error fails. (from compare-uscis-filing-receipt C-008, C-009, C-025)
- A delivery on a weekend or federal holiday, with a receipt date on the next business day, is expected lockbox timing. Record both dates and the timing. Marking the receipt date as wrong fails. A gap past the next business day, or a filing date the applicant stated that matches neither date, is a discrepancy. (from compare-uscis-filing-receipt C-010, C-011, C-012)
- When the internal checklist states a fee that differs from the cover letter and from the amount actually paid, the checklist is the stale document. The amount paid is the fact. Changing the payment to match the checklist fails. Any statement of which dollar amount is the current fee is [VERIFY against current USCIS source]. (from compare-uscis-filing-receipt C-016, C-017, C-018, C-025)
- A notice the file expected and does not contain is a missing document. Name the notice. (from compare-uscis-filing-receipt C-019)
- For the trip list and the address history, reconcile the set: how many entries, how many matched a document, how many had no document. A gap with no counts fails. (from compare-i C-020, C-021, C-022, C-023, C-024)
- A person in the case with no document is a missing document. A document for someone who is not the applicant is not this case's evidence. (from compare-i C-001, C-002, C-003, C-023)
- A document the case still relies on, whose validity has ended, is a gap. State the end date and the period the document was supposed to cover. (from compare-i C-009, C-010, C-011, C-012)
- The correction for a bad or missing document is a new current document. Backdating the original fails. (from compare-i C-031, C-032)
- Map each worksheet fact to the document that supports it. A fact the document fully supports is a non-issue, written down so a later pass does not flag it. (from compare-immigration C-029, C-030, C-031, C-032, C-039; compare-job-requirements C-028, C-029)
- Count trips, addresses, and presence only inside the period the rules engine already marked. Leave time outside that period out, and keep time the documents show inside it. Computing the period in the finding fails. (from compare-immigration C-006, C-007, C-008, C-009)
- When a document has an English translation, compare every name, date, and number between the original and the translation. A mismatch is a discrepancy citing both. (from extract-key-terms C-039, C-040)
- A transposed digit in a letter or summary, where the underlying record differs, is an error. Name every document that repeated the bad figure. (from extract-key-terms C-039, C-040, C-041, C-042)
- A document that is still valid on the date it will be used is not stale. Say so in the non_issue items. A document that expires before that date is a timing risk. (from consular-processing-packet C-023, C-024)
- A prior visa refusal, or a closed matter the file already describes, is context. Calling it a substantive bar fails. The legal effect goes to the attorney as a memo. (from consular-processing-packet C-021, C-027)
- A blank field the form asks for, or a stretch of address history the form asks for and does not contain, is a gap. Cite the form and the missing dates. (from consular-processing-packet C-015, C-017)
- A shared count (children, household members, or trips) that differs across documents is a discrepancy. When the corrected count still meets the threshold the rules engine already applied, say that. Treating the arithmetic mismatch as an eligibility failure fails. (from consular-processing-packet C-010, C-012)
- Every issue names its source documents. The memo includes short non_issue items. (from consular-processing-packet C-028, C-030; compare-job-requirements C-004)
- The same name, date of birth, A-Number, address, and trip dates are checked across the whole packet in one pass, not one form at a time. (from compare-job-requirements C-004, C-013)
- Cite only documents that actually contain the field in question. A `source_document_ids` entry for a document that does not hold that field fails. (from paralegal_notes.md; the smoke baseline cited `doc_green_card` on a trip-return finding the card does not contain)
- Blocking issues are review_items only; task findings are for non-blocking issues. Writing a blocking issue again as a task fails. (from paralegal_notes.md; the smoke baseline filed the trip-return conflict as both a review_item and a task)
- Severity follows the playbook's severity scale; mark any legal threshold as [VERIFY against current USCIS source]. A rank the scale does not use fails. (from paralegal_notes.md)
- When a document conflicts with a stated fact, also reference the conflicting fact (add a `source_facts` field listing fact fields). A conflict with a fact and no `source_facts` fails. (from paralegal_notes.md)
- A two-sided document (green card, driver's license, state ID) with only one side in the file is a gap. Use document_type '<type>_back' and key 'doc:<type>_back:'. Rate it Moderate. (from paralegal_notes.md)

## Severity scale

LAB uses four ranks. Use the same words here.
- **Critical.** A digit difference in an A-Number. A trip date that disagrees with a passport stamp by enough to cross a residence or presence threshold [VERIFY against current USCIS source]. A draft count of trips or days that the stamps and the worksheet do not support. A required identity or travel document that is absent.
- **High.** A document the filing still needs and that has expired, when a filing date is already set. A receipt the file expected and does not contain, when a planned filing date depends on it. A trip date that disagrees with a passport stamp but does not cross a threshold.
- **Moderate.** A middle name omitted or misspelled where the rest of the name matches. A blank stretch of address history. A children or household count that differs, when the corrected count still meets the rules engine's threshold.
- **Low.** Capitalization, punctuation, or a trailing period on the same spelling.
- A false-alarm guard is not a Low finding. Expected lockbox timing, a fee component receipted on its own notice, a document still valid on the date it will be used, and a fact the document fully supports are non-issues. They go on the non_issue items with no severity.

## Every finding must include

- **Issue.** What disagrees, what is missing, or what is stale.
- **Source documents.** The document id for every value you quote. Only documents that contain the field.
- **source_facts.** The fact fields, when a document conflicts with a stated fact.
- **Severity.** Critical, High, Moderate, or Low, from the scale above. Omit this only for a non-issue. A legal threshold is [VERIFY against current USCIS source].
- **Impact.** What the conflict does to identity, to a counted trip or address, or to the fee or edition check. Stop before a legal conclusion.
- **Recommended next step.** A concrete staff action: request a named document, read a named field back, or send a memo to the attorney. Backdating is never the step.

## Worked examples

Made-up case. Mateo Luis Ortega is not a real applicant.
**Example 1. Middle name.**
- Issue: The green card and the worksheet print the middle name Luis. The passport biographical page prints Luiz.
- Sources: green card transcript; passport biographical page; N-400 worksheet.
- Severity: Moderate.
- Impact: A later form can attach the file to the wrong spelling. The surname, date of birth, and A-Number match, so this is not an identity break.
- Next step: Post a gap asking for a document that shows the legal spelling of the middle name; the client liaison asks the client. Do not alter the green card transcript.

**Example 2. Lockbox timing, written as a non-issue.**
- Issue: None. FedEx delivered the packet on Saturday, and the receipt date is the following Monday.
- Sources: mail log; USCIS receipt notice.
- Severity: none. This is a non-issue.
- Impact: The one-business-day gap matches weekend lockbox timing. The receipt date stands.
- Next step: None. Leave it off the queue.

## Out of scope

You give no legal advice and no prediction that the applicant is eligible, approved, or will be fine. You do not file. You do not apply H-1B, PERM, LCA, or EB rules to a naturalization file; those LAB checks contribute only the patterns above (compare, count, cite, and withhold a flag when the documents already agree). Legal judgment, including whether an absence breaks continuous residence or whether a record is a bar, goes to the supervising attorney as a memo.
