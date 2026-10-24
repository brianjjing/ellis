"""Demo helpers (only on clinics with is_demo=true): fill answers as if the applicant had given them.

Every fact written here carries provenance {"simulated": true} and the UI labels it "Simulated".
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import Case, now
from . import case_service as cs
from . import catalog


def simulate_answers(s: Session, case: Case, answers: dict[str, Any], actor: str = "demo",
                     only_missing: bool = True) -> list[str]:
    written = []
    if "consent" in answers and not cs.consent_given(s, case):
        cs.record_fact(s, case, "consent", True, actor=actor, actor_type="system", provenance={"simulated": True})
        written.append("consent")
    for field, value in answers.items():
        if field == "consent":
            continue
        d = catalog.field_def(field)
        if d is None:
            continue
        cur = cs.current_facts(s, case.id).get(field)
        if only_missing and cur is not None and cur.status == "confirmed":
            continue
        if cur is not None and cur.value == catalog.DEFERRED:
            continue
        cap = d.get("capture", "V")
        try:
            if cap.startswith("S") or cap == "P":
                cs.secure_entry(s, case, field, value, actor=actor, actor_type="applicant")
            elif cap == "E":
                if field.endswith(".to"):
                    cs._insert_fact(s, case, field, value, "confirmed", "derived", proposed_by=actor,
                                    provenance={"simulated": True})
                continue
            else:
                res = cs.record_fact(s, case, field, value, actor=actor, actor_type="system",
                                     provenance={"simulated": True}, is_correction=cur is not None)
                if res.get("stopped"):
                    written.append(field)
                    continue
                f = cs.current_facts(s, case.id).get(field)
                if f is not None and f.status in ("proposed",) and f.value == res["fact"]["value"]:
                    f.status = "confirmed"
                    f.confirmed_at = now()
                    cs.emit(s, case, "fact.confirmed", {"field": field, "fact_id": f.id, "via": "simulated"},
                            "system", actor)
            written.append(field)
        except cs.CaseError:
            continue
    cs.evaluate_rules(s, case)
    cs.after_fact_change(s, case)
    return written
