"""Staff-agent runner: dispatcher (events → debounced jobs) + workers (claim → context → run → validate → apply).

    python -m ellis.agents.runner             # standalone worker; the API also runs one in-process by default

Debounce: events are folded into one pending job per (case, agent); the job runs ~3 s after the last event.
Claiming uses FOR UPDATE SKIP LOCKED on Postgres. One run per (case, agent) at a time; max 2 per case.
Invalid output: one retry with the validation error; then the job fails, a board task says so, nothing is written.
"""

from __future__ import annotations

import concurrent.futures
import logging
import secrets
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from ..config import settings
from ..db import AgentRun, Case, Event, Job, Task, is_postgres, now, session_scope
from ..services import catalog
from .backends import BackendError, get_backend
from .context import build_context, context_hash
from .proposals import ValidationError, apply_proposal, validate_envelope

log = logging.getLogger("ellis.agents")
RUN_TIMEOUT_S = 45
MAX_PER_CASE = 2


def wakes(ev: Event) -> list[str]:
    """The routing table (deterministic; costs no credits)."""
    k, p = ev.kind, ev.payload or {}
    if ev.actor_type == "agent":
        return []
    field = p.get("field") or ""
    out: list[str] = []
    if k in ("fact.recorded", "fact.corrected", "fact.confirmed"):
        out.append("case_manager")
        if catalog.is_date_field(field) or k == "fact.corrected":
            out.append("docketing_clerk")
        if catalog.is_material(field) or field.startswith(("background.", "trips[", "employment", "name")):
            out.append("qa_reviewer")
        if k == "fact.confirmed" and (catalog.field_def(field) or {}).get("capture", "").startswith("D"):
            out.append("doc_paralegal")
        if field.startswith("fee."):
            out.append("doc_paralegal")
    elif k == "flag.raised":
        out += ["case_manager", "doc_paralegal"]
        if p.get("speed") != "stop_now":
            out.append("qa_reviewer")
    elif k in ("doc.uploaded", "doc.extracted", "doc.extraction_failed"):
        out += ["doc_paralegal", "case_manager"]
    elif k == "review.decision":
        out += ["case_manager", "qa_reviewer"]
    elif k in ("session.ended", "consent.given", "gap.declined", "section.deferred", "review.reopened"):
        out.append("case_manager")
    elif k == "case.state_changed":
        out += ["case_manager", "qa_reviewer"]
        if p.get("to") == "signed":
            out.append("docketing_clerk")
    elif k == "derived.computed":
        out.append("docketing_clerk")
    return list(dict.fromkeys(out))


class Runner:
    def __init__(self, backend=None, debounce_s: float | None = None):
        self.backend = backend or get_backend()
        self.debounce = settings.agent_debounce_s if debounce_s is None else debounce_s
        self.cursor: int | None = None
        self.stop = threading.Event()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")

    # ---------------------------------------------------------------- dispatcher
    def dispatch_new_events(self) -> int:
        with session_scope() as s:
            if self.cursor is None:
                self.cursor = s.scalar(select(func.max(Event.id))) or 0
                return 0
            evs = list(s.scalars(select(Event).where(Event.id > self.cursor).order_by(Event.id).limit(500)))
            for ev in evs:
                self.cursor = ev.id
                if ev.case_id is None:
                    continue
                for agent in wakes(ev):
                    self._enqueue(s, ev, agent)
            return len(evs)

    def _enqueue(self, s, ev: Event, agent: str) -> None:
        j = s.scalars(select(Job).where(Job.case_id == ev.case_id, Job.agent == agent, Job.status == "queued")).first()
        nb = now() + timedelta(seconds=self.debounce)
        if j is None:
            s.add(Job(clinic_id=ev.clinic_id, case_id=ev.case_id, agent=agent, trigger_event=ev.id,
                      trigger_events=[ev.id], status="queued", not_before=nb))
        else:
            j.trigger_events = [*(j.trigger_events or []), ev.id][-50:]
            j.not_before = nb

    # ---------------------------------------------------------------- workers
    def claim(self) -> Job | None:
        with session_scope() as s:
            q = (select(Job).where(Job.status == "queued", Job.not_before <= now()).order_by(Job.id).limit(10))
            if is_postgres():
                q = q.with_for_update(skip_locked=True)
            for j in s.scalars(q):
                running = s.scalars(select(Job).where(Job.case_id == j.case_id, Job.status == "running")).all()
                if any(r.agent == j.agent for r in running) or len(running) >= MAX_PER_CASE:
                    continue  # one run at a time per (case, agent): stays queued for a rerun
                j.status = "running"
                j.claimed_at = now()
                j.run_id = f"run_{secrets.token_hex(4)}"
                s.flush()
                s.expunge(j)
                return j
        return None

    def run_job(self, job: Job) -> dict[str, Any]:
        t0 = time.time()
        with session_scope() as s:
            case = s.get(Case, job.case_id)
            ctx = build_context(s, case, job.trigger_events)
        if getattr(self.backend, "asynchronous", False):
            try:
                self.backend.dispatch(job.agent, job.case_id, f"events {job.trigger_events}", job.run_id)
                self._finish(job, "dispatched")
            except Exception as e:  # noqa: BLE001
                self._fail(job, str(e), title=f"Agent could not start ({job.agent}): {str(e)[:160]}")
            return {"dispatched": True}
        error = None
        env = None
        invalid = True  # False when the backend itself failed (not configured, unreachable, timed out)
        for attempt in range(2):
            try:
                fut = self.pool.submit(self.backend.run, job.agent, ctx, job.run_id, error)
                raw = fut.result(timeout=RUN_TIMEOUT_S)
                env = validate_envelope(raw, job.agent, job.case_id)
                break
            except (ValidationError, ValueError, KeyError, TypeError, BackendError) as e:
                error = str(e)[:1500]
                env = None
                invalid = not isinstance(e, BackendError)
            except concurrent.futures.TimeoutError:
                error = f"timeout after {RUN_TIMEOUT_S}s"
                env = None
                invalid = False
                break
        if env is None:
            self._fail(job, error or "invalid output", ctx,
                       title=None if invalid else f"Agent run failed ({job.agent}): {(error or '')[:160]}")
            return {"failed": True, "error": error}
        ms = int((time.time() - t0) * 1000)
        with session_scope() as s:
            res = apply_proposal(s, env, backend=self.backend.name, ms=ms, trigger_events=job.trigger_events,
                                 model=getattr(self.backend, "model", None))
            run = s.get(AgentRun, env.run_id)
            if run is not None:
                run.input_hash = context_hash(ctx)
        self._finish(job, "done")
        return res

    def _finish(self, job: Job, status: str) -> None:
        with session_scope() as s:
            j = s.get(Job, job.id)
            j.status = status
            j.finished_at = now()

    def _fail(self, job: Job, error: str, ctx: dict | None = None, title: str | None = None) -> None:
        with session_scope() as s:
            j = s.get(Job, job.id)
            j.status = "failed"
            j.error = error
            j.finished_at = now()
            case = s.get(Case, job.case_id)
            s.add(AgentRun(id=job.run_id, clinic_id=case.clinic_id, case_id=case.id, agent=job.agent,
                           backend=self.backend.name, trigger_events=job.trigger_events, status="failed",
                           output={"error": error}, ts=now()))
            s.add(Task(clinic_id=case.clinic_id, case_id=case.id, agent=job.agent, kind="system",
                       title=title or f"Agent output invalid ({job.agent}): nothing was written", proposed_by="runner",
                       ts=now()))
            from ..services import case_service as cs
            cs.emit(s, case, "agent.run_failed", {"agent": job.agent, "run_id": job.run_id, "error": error[:300]},
                    "system", "runner")

    def drain(self, max_jobs: int = 100) -> int:
        """Run every due job now (tests / evals)."""
        n = 0
        while n < max_jobs:
            j = self.claim()
            if j is None:
                break
            self.run_job(j)
            n += 1
        return n

    def settle(self, rounds: int = 6) -> int:
        """Dispatch + run until quiet (tests / evals use debounce 0)."""
        total = 0
        for _ in range(rounds):
            self.dispatch_new_events()
            n = self.drain()
            total += n
            if n == 0:
                self.dispatch_new_events()
                if self.drain() == 0:
                    break
        return total

    def loop(self, interval: float = 0.5) -> None:
        log.info("agent runner started (backend=%s)", self.backend.name)
        while not self.stop.is_set():
            try:
                self.dispatch_new_events()
                while True:
                    j = self.claim()
                    if j is None:
                        break
                    self.pool.submit(self._safe_run, j)
            except Exception:  # noqa: BLE001
                log.exception("runner loop error")
            self.stop.wait(interval)

    def _safe_run(self, j: Job) -> None:
        try:
            self.run_job(j)
        except Exception as e:  # noqa: BLE001
            log.exception("agent run crashed")
            try:
                self._fail(j, f"crash: {e}", title=f"Agent run crashed ({j.agent}): {str(e)[:160]}")
            except Exception:  # noqa: BLE001
                pass


_runner: Runner | None = None


def start_background_runner() -> Runner:
    global _runner
    if _runner is None:
        _runner = Runner()
        # requeue jobs left running by a previous process
        with session_scope() as s:
            for j in s.scalars(select(Job).where(Job.status == "running")):
                j.status = "queued"
        threading.Thread(target=_runner.loop, daemon=True, name="agent-runner").start()
    return _runner


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from ..db import create_all
    create_all()
    Runner().loop()
