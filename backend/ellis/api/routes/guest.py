"""/api/guest/chat: the logged-out guide. Rate-limited; never logs bodies; writes nothing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ...services import auth, case_service as cs, guest
from ..deps import err
from .auth import Turn

router = APIRouter(prefix="/api/guest", tags=["guest"])


class ChatReq(BaseModel):
    messages: list[Turn] = []
    answers: dict[str, Any] = {}


@router.post("/chat")
def chat(body: ChatReq, request: Request) -> dict[str, Any]:
    ip = request.client.host if request.client else "?"
    if auth.rate_limited(f"guest:{ip}", limit=30):
        raise err(429, "rate_limited", "Too many messages. Please wait a minute.")
    msgs = [{"who": m.who, "text": m.text[:2000]} for m in body.messages[-30:]]
    return guest.respond(msgs, body.answers, cs.today())
