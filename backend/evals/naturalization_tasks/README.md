# Naturalization eval tasks

These cases grade Ellis staff work with the same task file Harvey's Legal Agent Benchmark uses. One `task.json` per case. The case passes only when every criterion passes.

This folder is not the LAB benchmark, and it is not a training set. The people and numbers in `documents/` are invented. LAB matter documents are not copied here. Role playbooks in `backend/prompts/playbooks/` generalize LAB's quality criteria into N-400 work. They do not restate LAB's facts.

## Schema

A case uses LAB's `task.json` fields:

- `title`
- `work_type`
- `instructions`
- `deliverables` (map of output filename to output filename)
- `criteria[]`, each with:
  - `id` (`C-001`, `C-002`, …)
  - `title`
  - `deliverables` (list of output filenames that criterion grades)
  - `match_criteria` (one binary test: `PASS if … FAIL if …`)

## All-pass grading

Grade each criterion on its own, PASS or FAIL, from `match_criteria`. The case passes when every criterion passes. One FAIL fails the case. There is no partial credit and no weighting.

## Case folder

`task.json` plus a `documents/` folder of short synthetic text. The instructions name those files. A planted defect is something the memo must catch. A planted non-issue is something the memo must leave unflagged.

## Example

[`trip-date-conflict/`](trip-date-conflict/task.json) is a document-comparison review, the kind of work the paralegal and QA playbooks describe.

The packet plants three things:

- a trip return date on the worksheet that disagrees with a passport admission stamp
- a middle name spelled differently on the passport than on the green card and the worksheet
- a Saturday lockbox delivery with a receipt date on the following Monday, which is ordinary timing and must not be flagged as a wrong receipt date

The shared A-Number, date of birth, and green-card date match on purpose. Flagging them is a fail.
