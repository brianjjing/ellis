# Paralegal holdout 02 — expected checklist

A correct run on `input.json` produces all of the following. Client language is Vietnamese.

- A `gap` with `document_type` `green_card_back` and key `doc:green_card_back:`. The green card extraction has only `front` in `sides_in_file`.
- That gap's applicant-facing label is Vietnamese. An English or Spanish label fails.
- A `review_item` with category `identifier_mismatch` on `a_number`: passport `[ANUM_1]` versus green card `[ANUM_2]`, one transposed digit. `source_document_ids` lists only `doc_passport` and `doc_green_card`.
- The A-Number conflict is a `review_item` only. It does not also appear as a `task`.
- The `a_number` `identifier_mismatch` review_item is rated Critical.
- `family_name_as_printed` is `Lumina` on the passport and `LUMINA` on the green card. Both use token `[FAMILY_2]`. This is Low or a `non_issue`. It must NOT be rated Critical.
- The output must NOT treat that capitalization difference as a different person or as a `name_mismatch`. Given `[GIVEN_2]` and middle `[MIDDLE_3]` match and must NOT be flagged.
- Output is a single JSON envelope with nothing outside it.
- Exhibits are numbered from 1 in order.
