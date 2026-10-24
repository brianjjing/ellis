"""Extract Harvey LAB immigration criteria into per-role JSON.

Deterministic. No model calls. Reads only ``tasks/immigration/**/task.json``
from the vendored harvey-labs tree and writes ``lab_extracted/<role>.json``.

This pulls work patterns and quality criteria. It is not a training set, and it
does not copy LAB matter documents.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMMIGRATION = HERE / "vendor" / "harvey-labs" / "tasks" / "immigration"
HARVEY_ROOT = HERE / "vendor" / "harvey-labs"
OUT_DIR = HERE / "lab_extracted"

# Folder paths are relative to tasks/immigration and must match the repo.
# A name that is not an exact task directory is reported and skipped.
PARALEGAL = [
    "compare-uscis-filing-receipt-against-original-petition-submission",
    "identify-issues-in-consular-processing-packet",
    "compare-immigration",
    "compare-job-requirements-against-candidate-credentials",
    "compare-i",
    "extract-key-terms-from-foreign-credential-evaluations",
]
QA_REVIEWER = [
    "identify-rfe-issues/scenario-01",
    "identify-rfe-issues/scenario-02",
    "identify-h1b-qualification-issues",
    "compare-draft-eb",
    "identify-issues-in-employer-support-documentation-for-h",
]
DOCKET_FULL = [
    "extract-filing-requirements-from-regulatory-guidance",
    "extract-eligibility-requirements-from-visa-category-regulations",
]
DOCKET_FILTERED = "compare-draft-eb"

# Union, in role order. compare-draft-eb is already in the QA list.
ALL_TASKS = list(dict.fromkeys([*PARALEGAL, *QA_REVIEWER, *DOCKET_FULL]))

_DOCKET_EB = re.compile(
    r"stale|staleness|edition\s+date|form\s+edition|\bedition\b|\bfees?\b|filing fee",
    re.IGNORECASE,
)
# Worded so "recommendation letter" and "priority date" do not match, and so a
# filename like "categories.docx" is not read as a severity ranking.
_SEVERITY = re.compile(
    r"\bseverity\b"
    r"|\b(?:critical|high|moderate|low)\s+priority\b"
    r"|\b(?:critical|high|moderate|low)\s+severity\b"
    r"|\b(?:classif\w*|categoriz\w*|rat(?:e|es|ed|ing)|assign\w*)\b"
    r"(?:\W+\w+){0,14}\W+\b(?:critical|high|moderate|low)\b",
    re.IGNORECASE,
)
_PRIORITY = re.compile(
    r"\bprioritiz(?:e|es|ed|ing)\b"
    r"|\bprioriti[sz]ation\b"
    r"|\b(?:critical|high|moderate|low)\s+priority\b"
    r"|\bpriority\s*/\s*severity\b"
    r"|\bseverity\s*/\s*priority\b"
    r"|\bpriority\s+(?:rating|level|classification)s?\b"
    r"|\burgenc(?:y|ies)\b"
    r"|\burgent(?:ly)?\b"
    r"|\baction items?\b",
    re.IGNORECASE,
)
_REMEDIAL = re.compile(
    r"\bremediat(?:e|es|ed|ing|ion)\b"
    r"|\bremedial\b"
    r"|\bcorrective\b"
    r"|\brecommend(?:s|ed|ing)?\b",
    re.IGNORECASE,
)


def index_tasks(root: Path) -> dict[str, Path]:
    """Map ``tasks/immigration``-relative directory -> ``task.json`` path."""
    if not root.is_dir():
        return {}
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("task.json")):
        found[path.parent.relative_to(root).as_posix()] = path
    return found


def _blob(text_title: str, text_match: str) -> str:
    return f"{text_title}\n{text_match}"


def docket_eb_keep(criterion: dict) -> list[str]:
    blob = _blob(criterion.get("title", ""), criterion.get("match_criteria", ""))
    return ["staleness, edition date, or fee"] if _DOCKET_EB.search(blob) else []


def case_manager_keep(criterion: dict) -> list[str]:
    blob = _blob(criterion.get("title", ""), criterion.get("match_criteria", ""))
    tags: list[str] = []
    if _SEVERITY.search(blob):
        tags.append("severity")
    if _PRIORITY.search(blob):
        tags.append("prioritization")
    if _REMEDIAL.search(blob):
        tags.append("remedial")
    return tags


def load_task(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    source = path.relative_to(HARVEY_ROOT).as_posix()
    return {
        "source_task_path": source,
        "title": data["title"],
        "work_type": data.get("work_type"),
        "instructions": data["instructions"],
        "criteria": data["criteria"],
    }


def _select(task: dict, keep) -> tuple[list[dict], dict[str, list[str]]]:
    chosen: list[dict] = []
    tags: dict[str, list[str]] = {}
    for criterion in task["criteria"]:
        matched = keep(criterion)
        if not matched:
            continue
        chosen.append(criterion)
        tags[criterion["id"]] = matched
    return chosen, tags


def _entry(task: dict, criteria: list[dict], criteria_filter: str | None, tags: dict[str, list[str]] | None) -> dict:
    entry = {
        "source_task_path": task["source_task_path"],
        "title": task["title"],
        "work_type": task["work_type"],
        "instructions": task["instructions"],
        "criteria_filter": criteria_filter,
        "criteria": criteria,
    }
    if tags is not None:
        entry["criteria_match_tags"] = tags
    return entry


def collect(
    names: list[str],
    index: dict[str, Path],
    keep=None,
    criteria_filter: str | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """Load tasks in the requested order.

    ``keep`` filters criteria. When it is None, the full criteria list is kept.
    Missing folder names are returned and not guessed from prefixes.
    The third list is tasks that exist but had zero criteria pass ``keep``.
    """
    tasks: list[dict] = []
    missing: list[str] = []
    no_match: list[str] = []
    for name in names:
        path = index.get(name)
        if path is None:
            missing.append(name)
            print(f"MISSING task folder: {name}", file=sys.stderr)
            continue
        loaded = load_task(path)
        if keep is None:
            tasks.append(_entry(loaded, loaded["criteria"], criteria_filter, None))
            continue
        chosen, tags = _select(loaded, keep)
        if not chosen:
            no_match.append(name)
            continue
        tasks.append(_entry(loaded, chosen, criteria_filter, tags))
    return tasks, missing, no_match


def _payload(role: str, note: str, tasks: list[dict], missing: list[str], no_match: list[str]) -> dict:
    return {
        "role": role,
        "note": note,
        "missing_task_folders": missing,
        "tasks_with_no_matching_criteria": no_match,
        "task_count": len(tasks),
        "criterion_count": sum(len(task["criteria"]) for task in tasks),
        "tasks": tasks,
    }


def extract(index: dict[str, Path] | None = None) -> dict[str, dict]:
    index = index_tasks(IMMIGRATION) if index is None else index
    note = (
        "Work patterns and quality criteria extracted from Harvey Legal Agent Benchmark "
        "(LAB) tasks/immigration. Not a training set. Matter documents were not copied."
    )
    paralegal, missing_p, none_p = collect(PARALEGAL, index)
    qa, missing_q, none_q = collect(QA_REVIEWER, index)
    docket, missing_d, none_d = collect(DOCKET_FULL, index)
    filtered, missing_f, none_f = collect(
        [DOCKET_FILTERED],
        index,
        keep=docket_eb_keep,
        criteria_filter="staleness, edition dates, or fees",
    )
    docket.extend(filtered)
    manager, missing_m, none_m = collect(
        ALL_TASKS,
        index,
        keep=case_manager_keep,
        criteria_filter="severity ranking, prioritization, or recommending remedial or corrective action",
    )
    return {
        "paralegal": _payload("paralegal", note, paralegal, missing_p, none_p),
        "qa_reviewer": _payload("qa_reviewer", note, qa, missing_q, none_q),
        "docket_clerk": _payload("docket_clerk", note, docket, missing_d + missing_f, none_d + none_f),
        "case_manager": _payload("case_manager", note, manager, missing_m, none_m),
    }


def write(payloads: dict[str, dict], out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for role, payload in payloads.items():
        path = out_dir / f"{role}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(
            f"{role}: {payload['task_count']} tasks, {payload['criterion_count']} criteria"
            f" -> {path.relative_to(HERE.parent.parent) if HERE.parent.parent in path.parents else path}"
        )
        if payload["missing_task_folders"]:
            print(f"  missing: {', '.join(payload['missing_task_folders'])}")
        if payload["tasks_with_no_matching_criteria"]:
            print(f"  no matching criteria: {', '.join(payload['tasks_with_no_matching_criteria'])}")
        for task in payload["tasks"]:
            if not task.get("criteria_match_tags"):
                continue
            ids = ", ".join(f"{cid}[{'+'.join(tags)}]" for cid, tags in task["criteria_match_tags"].items())
            folder = task["source_task_path"].removeprefix("tasks/immigration/").removesuffix("/task.json")
            print(f"  {folder}: {ids}")


def main() -> int:
    if not IMMIGRATION.is_dir():
        print(f"MISSING vendor tree: {IMMIGRATION}", file=sys.stderr)
        return 1
    payloads = extract()
    write(payloads)
    missing = sorted({name for payload in payloads.values() for name in payload["missing_task_folders"]})
    print("Missing task folders: " + (", ".join(missing) if missing else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
