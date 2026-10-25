# Paralegal holdout 03 — expected checklist

A correct run on `input.json` produces all of the following. Client language is Spanish. `criminal_history_detail` is stop-now.

- A `review_item` with category `document_conflict` on `marriage_date`: original `2015-09-01` versus translation `2015-09-10`.
- That finding cites both `doc_marriage_original` and `doc_marriage_translation`. It cites no other document.
- The marriage-date conflict includes `source_facts` listing `marriage_date`.
- The marriage-date conflict is a `review_item` only. It does not also appear as a `task`.
- Name tokens and `[PLACE_1]` match on the original and the translation. The output must NOT flag those fields.
- No `gap` is created for `flag:arrest:` or for `criminal_history_detail`.
- The arrest flag appears only as an internal `task`. That task must NOT ask the client for a document.
- Output is a single JSON envelope with nothing outside it.
- Exhibits are numbered from 1 in order.
