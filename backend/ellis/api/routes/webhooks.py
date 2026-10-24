"""Creao webhook: run results arrive here (at least once). Dedupe on X-Creao-Delivery-Id and run_id, return 2xx
immediately, apply through the same proposal validation path as local agents."""

from __future__ import annotations

import hmac
import os
import threading
from typing import Any

from fastapi import APIRouter, Request

from ...db import session_scope
from ...agents.proposals import apply_proposal, validate_envelope
from ..deps import err

router = APIRouter(tags=["webhooks"])
_seen: set[str] = set()
_lock = threading.Lock()


@router.post("/webhooks/creao")
async def creao(request: Request) -> dict[str, Any]:
    secret = os.environ.get("CREAO_WEBHOOK_SECRET")
    if secret and not hmac.compare_digest(request.headers.get("x-creao-signature", ""), secret):
        raise err(401, "unauthorized", "bad signature")
    delivery = request.headers.get("x-creao-delivery-id", "")
    with _lock:
        if delivery and delivery in _seen:
            return {"ok": True, "duplicate": True}
        if delivery:
            _seen.add(delivery)
    body = await request.json()
    envelope = body.get("output") or body.get("result") or body

    def work():
        try:
            env = validate_envelope(envelope, envelope.get("agent"), envelope.get("case_id"))
        except Exception:  # noqa: BLE001 - invalid output: nothing is written
            return
        with session_scope() as s:
            apply_proposal(s, env, backend="creao")
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True}
