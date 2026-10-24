"""FastAPI app: the Case API. The only door into the data.

    uv run uvicorn ellis.api.app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from ..config import BACKEND_DIR, settings
from ..db import create_all
from ..services.case_service import CaseError

log = logging.getLogger("ellis")


class NoToolBodies(logging.Filter):
    """Never log request bodies or query strings of /tools/* (stop-now text must not reach any log)."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "/tools/" not in msg or "body" not in msg.lower()


def _warn_insecure_defaults() -> None:
    """The tool/session secrets (and the vault key, which falls back to a hash of the session secret) default
    to fixed, publicly-known dev values. Fine for local/demo use; silent in a real deployment, it means case
    data (including the vault-encrypted A-number, SSN, passport number and income) isn't actually protected.
    """
    if settings.tool_secret == "dev-tool-secret":
        log.warning("ELLIS_TOOL_SECRET is unset; using the default dev value. Set a real secret before any "
                   "non-local use.")
    if settings.session_secret == "dev-session-secret-change-me":
        log.warning("ELLIS_SESSION_SECRET is unset; using the default dev value. Session cookies and the "
                   "vault encryption key fallback both derive from this -- set a real secret before any "
                   "non-local use.")


def create_app(start_workers: bool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        _warn_insecure_defaults()
        if os.environ.get("ELLIS_AUTO_CREATE", "1") == "1":
            create_all()
        run = settings.run_agents_inprocess if start_workers is None else start_workers
        if run:
            from ..agents.runner import start_background_runner
            start_background_runner()
        if settings.cartesia_api_key:
            from ..voice.cartesia import warm_voices
            warm = asyncio.create_task(warm_voices())  # noqa: F841 - held by this frame so it isn't collected
        yield

    app = FastAPI(title="Ellis Case API", version="0.1.0", lifespan=lifespan)
    logging.getLogger("uvicorn.access").addFilter(NoToolBodies())

    from .routes import applicant, clinic, tools, voice, webhooks

    app.include_router(tools.router)
    app.include_router(applicant.router)
    app.include_router(applicant.files_router)
    app.include_router(clinic.router)
    app.include_router(voice.router)
    app.include_router(webhooks.router)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(CaseError)
    async def case_error(_: Request, exc: CaseError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message,
                                                                        "field": exc.field}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request",
                                                                "message": "invalid request",
                                                                "details": exc.errors()[:5]}})

    @app.get("/api/health")
    def health():
        return {"ok": True, "agent_backend": settings.agent_backend,
                "voice": {"cartesia": bool(settings.cartesia_api_key)},
                "liaison_brain": "claude" if settings.anthropic_api_key else "scripted"}

    # Serve the built web client when present (single-origin deploys); dev uses the Vite proxy.
    dist = Path(os.environ.get("ELLIS_WEB_DIST", BACKEND_DIR.parent / "frontend" / "dist"))
    if dist.exists():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
