#!/usr/bin/env bash
# One command for local dev: seed the synthetic demo, run the Case API (+ in-process agent runner) and the web app.
#   ./scripts/dev.sh            # uses backend/.env (DATABASE_URL defaults to SQLite if unset)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ELLIS_TODAY="${ELLIS_TODAY:-2026-10-23}"   # the flows are written for Fri Oct 23, 2026
cd "$ROOT/backend"
uv sync --extra llm >/dev/null
# this machine's Python has no system CA bundle wired up (SSL_CERT_FILE unset), so outbound HTTPS --
# including every Cartesia and Anthropic call -- fails cert verification and falls back silently
# (Cartesia TTS failing means the browser's own, much more robotic, speechSynthesis takes over).
export SSL_CERT_FILE="$(uv run python -c 'import certifi; print(certifi.where())')"
uv run python -m seed.load
uv run uvicorn ellis.api.app:app --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npx vite --port 5173
