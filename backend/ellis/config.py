"""Settings from the environment and versioned YAML config files."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"
PROMPTS_DIR = BACKEND_DIR / "prompts"

load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


class Settings:
    @property
    def database_url(self) -> str:
        return env("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'ellis.db'}")

    @property
    def tool_secret(self) -> str:
        return env("ELLIS_TOOL_SECRET", "dev-tool-secret")

    @property
    def session_secret(self) -> str:
        return env("ELLIS_SESSION_SECRET", "dev-session-secret-change-me")

    @property
    def vault_key(self) -> str | None:
        return env("VAULT_KEY")

    @property
    def anthropic_api_key(self) -> str | None:
        return env("ANTHROPIC_API_KEY")

    @property
    def cartesia_api_key(self) -> str | None:
        return env("CARTESIA_API_KEY")

    @property
    def files_dir(self) -> Path:
        p = Path(env("ELLIS_FILES_DIR", str(BACKEND_DIR / "data" / "files")))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def agent_backend(self) -> str:
        # skeleton (deterministic, no model) | anthropic | creao
        default = "anthropic" if self.anthropic_api_key else "skeleton"
        return env("ELLIS_AGENT_BACKEND", default)

    @property
    def run_agents_inprocess(self) -> bool:
        return env("ELLIS_RUN_AGENTS_INPROCESS", "1") == "1"

    @property
    def agent_debounce_s(self) -> float:
        return float(env("ELLIS_AGENT_DEBOUNCE_S", "3"))

    @property
    def public_base_url(self) -> str:
        return env("ELLIS_PUBLIC_BASE_URL", "http://localhost:5173")

    @property
    def liaison_model(self) -> str:
        return env("ELLIS_LIAISON_MODEL", "claude-haiku-5-5")

    @property
    def agent_model(self) -> str:
        return env("ELLIS_AGENT_MODEL", "claude-sonnet-5-5")

    @property
    def conversation_model(self) -> str:
        # drives the live conversation (LlmLiaison): tool-call reliability matters more here than
        # in the narrow field-extractor, so default to a stronger model than ELLIS_LIAISON_MODEL.
        return env("ELLIS_CONVERSATION_MODEL", "claude-sonnet-5-5")

    @property
    def conversation_engine(self) -> str:
        # llm (default when a key is present): Claude drives the conversation through tools.
        # scripted: the deterministic field-by-field liaison. Forced to scripted with no API key.
        default = "llm" if self.anthropic_api_key else "scripted"
        return env("ELLIS_CONVERSATION_ENGINE", default)

    @property
    def today_override(self) -> str | None:
        # Pin "today" for demos and tests (flows are written for Fri Oct 23, 2026).
        return env("ELLIS_TODAY")


settings = Settings()


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def rule_config_raw() -> dict[str, Any]:
    version = env("ELLIS_RULE_CONFIG", "2026.10-a")
    return _load(CONFIG_DIR / "rule_config" / f"{version}.yaml")


@lru_cache
def rule_config():
    from .rules.engine import RuleConfig
    return RuleConfig.from_dict(rule_config_raw())


@lru_cache
def fee_config():
    from .rules.engine import FeeConfig
    return FeeConfig.from_dict(_load(CONFIG_DIR / "fees.yaml"))


@lru_cache
def yaml_config(name: str) -> Any:
    return _load(CONFIG_DIR / name)
