# Paralegal smoke — expected checklist

A correct run on `input.json` produces all of the following.

- A `review_item` with category `document_conflict` on `trip_3_return` (voice `2023-05-20` vs passport entry stamp `2023-06-02`).
- A `review_item` with category `name_mismatch` (`[NAME_1]` on the passport vs `[NAME_2]` on the green card).
- A `gap` with key `flag:citation:` and a Spanish label.
- Exhibits numbered 1 and 2.
- No gap created for `criminal_history_detail` (stop-now).
- No flag on `a_number` (it matches).
- Every `source_document_ids` list cites only documents that contain that field.
- A blocking issue appears only as a `review_item`, never also as a `task`.
- * The `trip_3_return` review_item has `source_facts: ["trip_3_return"]` and cites only `doc_passport`.

  * The `trip_3_return` review_item is rated High, not Critical, and leaves the threshold question as `[VERIFY against current USCIS source]`.

  * The citation gap has `label_language: "es"`.

  * `a_number` appears as a `non_issue` item.

  * A `gap` with key `doc:green_card_back:` (the green card extraction has only front-side fields).

  * Output is a single JSON envelope with nothing outside it.
