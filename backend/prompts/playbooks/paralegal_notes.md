# Paralegal notes

Rules the paralegal playbook must include. Found in the baseline run at `backend/evals/naturalization_tasks/paralegal-smoke/baseline_output.json`.

- Cite only documents that actually contain the field in question.
- Blocking issues are review_items only; task findings are for non-blocking issues.
- Severity follows the playbook's severity scale; mark any legal threshold as [VERIFY against current USCIS source].
- When a document conflicts with a stated fact, also reference the conflicting fact (add a `source_facts` field listing fact fields).

Later edits, and why:

- Middle-name next step is a gap for a document that shows the legal spelling. The client liaison asks the client. The paralegal does not ask, and does not alter the green card transcript.
- A trip date against a passport stamp is Critical only when the gap is large enough to cross a residence or presence threshold. The threshold is [VERIFY against current USCIS source]. A disagreement that does not cross a threshold is High.
- The two credential-evaluation rules (compare two evaluations; record the evaluator's own credential) are replaced by one: compare every name, date, and number on an original with its English translation. N-400 files need that check, not a foreign-credential equivalency analysis. (from extract-key-terms C-039, C-040)
- Reconciliation is scoped to the trip list and the address history: how many entries, how many matched a document, how many had no document. It is not a whole-roster audit.
- Say `non_issue items`, not "non-issue list".
- Success criteria, the severity scale, "Every finding must include", and the worked-example fields are markdown bullet lists with no blank lines between items.
- A two-sided document with only one side in the file is a Moderate gap, `document_type` `<type>_back` and key `doc:<type>_back:`. The smoke run noticed the green card back was missing but raised no gap.
