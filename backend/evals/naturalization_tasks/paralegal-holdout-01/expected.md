# Paralegal holdout 01 — expected checklist

A correct run on `input.json` produces all of the following. Client language is English.

- A `review_item` with category `name_mismatch` on the middle name: passport `[MIDDLE_1]` versus green card `[MIDDLE_2]`. Given name `[GIVEN_1]` and family name `[FAMILY_1]` match. Severity is Moderate, not Critical.
- That name conflict includes `source_facts` listing `name.middle`, and `source_document_ids` lists only `doc_passport` and `doc_green_card`.
- The name conflict is a `review_item` only. It does not also appear as a `task`.
- A gap asks for a document that shows the legal spelling of the middle name. Its applicant-facing label is English.
- `trip_1_departure` `2022-06-04` and `trip_1_return` `2022-06-18` match the passport exit and entry stamps. Both are `non_issue` items. The output must NOT flag either date.
- Passport `expiration_date` `2031-08-14` is after `filing_date` `2026-11-01`. That is a `non_issue`. The output must NOT open a gap because the passport expires.
- `[ANUM_1]` is the only A-Number in the file. The output must NOT flag `a_number`.
- Output is a single JSON envelope with nothing outside it.
- Exhibits are numbered from 1 in order.
