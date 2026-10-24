"""In-process pub/sub that fans committed events out to WebSocket streams.

Events are published only after the DB transaction commits. Cross-process consumers (the agent
dispatcher) read the event table directly (and Postgres also fires NOTIFY case_events).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

_lock = threading.Lock()
_subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue, Callable[[dict], bool]]] = []


def subscribe(match: Callable[[dict], bool]) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    with _lock:
        _subs.append((asyncio.get_running_loop(), q, match))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    with _lock:
        _subs[:] = [s for s in _subs if s[1] is not q]


def publish(msg: dict[str, Any]) -> None:
    with _lock:
        subs = list(_subs)
    for loop, q, match in subs:
        try:
            if match(msg):
                loop.call_soon_threadsafe(_put, q, msg)
        except RuntimeError:  # loop closed
            pass


def _put(q: asyncio.Queue, msg: dict) -> None:
    if not q.full():
        q.put_nowait(msg)


def queue_after_commit(s: Session, msg: dict[str, Any]) -> None:
    s.info.setdefault("bus_pending", []).append(msg)


@sa_event.listens_for(Session, "after_commit")
def _after_commit(s: Session) -> None:
    pending = s.info.pop("bus_pending", [])
    for m in pending:
        publish(m)


@sa_event.listens_for(Session, "after_rollback")
def _after_rollback(s: Session) -> None:
    s.info.pop("bus_pending", None)
