# Paralegal holdout results

Graded `output.json` against `expected.md` in each `paralegal-holdout-*` folder. A case passes only when every checklist item passes.

| Case | Items passed | All-pass | Failures |
| --- | --- | --- | --- |
| paralegal-holdout-01 | 9/9 | yes | — |
| paralegal-holdout-02 | 9/9 | yes | — |
| paralegal-holdout-03 | 9/9 | yes | — |

## paralegal-holdout-01

- **PASS.** Middle-name `name_mismatch` is Moderate: `"category": "name_mismatch", "field": "name.middle", "severity": "Moderate"` and `"Passport middle_name prints [MIDDLE_1]; green card middle_name prints [MIDDLE_2]"` with `"Given name [GIVEN_1], family name [FAMILY_1] and A-Number [ANUM_1] are identical"`.
- **PASS.** `"source_document_ids": ["doc_passport", "doc_green_card"]` and `"source_facts": ["name.middle"]`.
- **PASS.** The name conflict is the only `review_item`. The tasks are `"Green card expiration date is not in the extraction, so staleness was not checked"` and `"Residence start date on the green card is not in the case facts"`.
- **PASS.** Gap label is English: `"label": "A document that shows the legal spelling of your middle name (for example, a birth certificate or a court order)", "label_language": "en"`.
- **PASS.** Both trip dates are `non_issue`: `"Passport exit stamp 2022-06-04 matches the stated departure 2022-06-04 exactly"` and `"Passport entry stamp 2022-06-18 matches the stated return 2022-06-18 exactly"`.
- **PASS.** Passport expiry is a `non_issue`: `"Passport expires 2031-08-14 and the filing date is 2026-11-01, so the passport is valid on the date it will be used and is not stale."` The only gap is `"document_type": "middle_name_legal_record"`.
- **PASS.** A-Number is a `non_issue`: `"Card prints [ANUM_1], the same value as the case fact. No digit difference to reconcile."`
- **PASS.** The file is one JSON object, `"case_id": "case_holdout_01"`, from the opening `{` through the closing `}`.
- **PASS.** Exhibits are `"exhibit": 1` on `doc_passport` and `"exhibit": 2` on `doc_green_card`.

## paralegal-holdout-02

- **PASS.** `"document_type": "green_card_back", "key": "doc:green_card_back:"` and `"pages_complete": "front only — the back side is not in the file"`.
- **PASS.** Gap label is Vietnamese: `"label": "Mặt sau của thẻ xanh (thẻ thường trú nhân) của quý vị", "label_language": "vi"`.
- **PASS.** `"category": "identifier_mismatch", "field": "a_number", "source_document_ids": ["doc_passport", "doc_green_card"]` and `"one digit transposed relative to [ANUM_1]"`.
- **PASS.** The A-Number conflict is the only `review_item`. Task titles are travel history, passport expiration, and residence start date.
- **PASS.** That review item has `"severity": "Critical"`.
- **PASS.** Capitalization is a `non_issue`: `"The printed strings differ only in capitalisation (Lumina on the passport, LUMINA on the card) ... no styling finding is raised."`
- **PASS.** `"Given name [GIVEN_2] appears identically"` and `"Middle name [MIDDLE_3] appears identically"` are both `non_issue`. The only review category is `identifier_mismatch`.
- **PASS.** The file is one JSON object, `"case_id": "case_holdout_02"`, from the opening `{` through the closing `}`.
- **PASS.** Exhibits are `"exhibit": 1` on `doc_passport` and `"exhibit": 2` on `doc_green_card`.

## paralegal-holdout-03

- **PASS.** `"category": "document_conflict", "field": "marriage_date"` and `"doc_marriage_original prints marriage_date 2015-09-01"` versus `"prints marriage_date 2015-09-10"`.
- **PASS.** `"source_document_ids": ["doc_marriage_original", "doc_marriage_translation"]`.
- **PASS.** `"source_facts": ["marriage_date"]`.
- **PASS.** The marriage-date conflict is the only `review_item`. The only task is `"Open arrest flag has no document and its section is stop-now"`.
- **PASS.** Names and place are `non_issue`, including `"Place [PLACE_1] matches between the original and the translation."`
- **PASS.** The only gap is `"document_type": "certified_translation", "key": "doc:certified_translation:"`. The arrest task says `"no client-facing gap was raised for it"`.
- **PASS.** The arrest task next step is `"Attorney decision on how to handle the arrest under the stop-now hold; no request to the client and no gap item until the hold is lifted."`
- **PASS.** The file is one JSON object, `"case_id": "case_holdout_03"`, from the opening `{` through the closing `}`.
- **PASS.** Exhibits are `"exhibit": 1` on `doc_marriage_original` and `"exhibit": 2` on `doc_marriage_translation`.
