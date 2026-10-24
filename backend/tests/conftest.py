"""Test setup: an isolated database (SQLite by default; set TEST_DATABASE_URL for Postgres), pinned date,
synchronous extraction, no in-process agent runner (tests drive it with debounce 0)."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="ellis-test-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["ELLIS_FILES_DIR"] = f"{_tmp}/files"
os.environ["ELLIS_TODAY"] = "2026-10-23"
os.environ["ELLIS_EXTRACTION_SYNC"] = "1"
os.environ["ELLIS_RUN_AGENTS_INPROCESS"] = "0"
os.environ["ELLIS_AGENT_BACKEND"] = "skeleton"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["CARTESIA_API_KEY"] = ""
os.environ["ELLIS_TOOL_SECRET"] = "test-secret"

import pytest  # noqa: E402

from ellis.db import reset_engine  # noqa: E402


@pytest.fixture()
def seeded():
    reset_engine()
    from seed import load
    load.load(reset=True)
    yield
    reset_engine()


@pytest.fixture()
def runner(seeded):
    from ellis.agents.runner import Runner
    r = Runner(debounce_s=0)
    r.dispatch_new_events()
    return r


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient
    from ellis.api.app import create_app
    with TestClient(create_app(start_workers=False)) as c:
        yield c
