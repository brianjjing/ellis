# Paralegal travel-smoke — expected checklist

A correct run on `input.json` produces all of the following.

## Travel candidates

- A `travel_candidate` for trip index 0 (departure 2021-06-10): `departure_source` is `i94` and the
  I-94 return date (2021-07-18) disagrees with the passport entry stamp (2021-07-20); the agent must
  flag this, not silently pick one date.
  * `source_document_ids` lists both `doc_i94` and `doc_passport`.

- A `travel_candidate` for trip index 1 (departure 2022-11-20): I-94 return is 2023-01-08, passport
  entry stamp is 2023-01-14 — a second date disagreement.
  * Both documents listed in `source_document_ids`.

- A `travel_candidate` for trip index 2 (departure 2024-03-05): no return record in either document.
  * `return_source` is `missing` and `return_date` is null.
  * `source_document_ids` contains `doc_i94` and `doc_passport`.

## Review items

- A `review_item` with category `document_conflict` for the trip 0 or trip 1 date disagreement
  (passport entry stamp vs. I-94 return date). The finding must not invent which date is correct —
  it must note the disagreement and ask the clinic to verify.

  * If the paralegal includes a `citation`, it must reference a real USCIS, eCFR, or Federal Register
    URL, not a placeholder. The quote must be ≤25 words.

## Non-issues

- Trip 2 departure (2024-03-05) is consistent across I-94 and passport exit stamp; the agent may
  record it as a `non_issue` with note explaining it matches.

## Guards

- No `travel_candidate` or `review_item` for the A-Number or full name (not a travel field).
- No trip data is written as a fact directly — all trips go through `travel_candidate` items so the
  client confirms by voice.
- Output is a single JSON envelope with nothing outside it.
- Every `source_document_ids` list cites only documents that actually contain the relevant stamps.

## Grading note

`[VERIFY against current USCIS source]` is acceptable anywhere a threshold or rule is cited.
The trip-date disagreement is the primary finding; the agent should not invent a resolution.
