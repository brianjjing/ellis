#!/usr/bin/env bash
# One command for local dev: seed the synthetic demo, run the Case API (+ in-process agent runner) and the web app.
#   ./scripts/dev.sh            # uses backend/.env (DATABASE_URL defaults to SQLite if unset)
# Python runs from the repo's .venv (see README "Quick start" to create it); this script never installs Python packages.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ELLIS_TODAY="${ELLIS_TODAY:-2026-10-23}"   # the flows are written for Fri Oct 23, 2026
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "No virtualenv at $ROOT/.venv. Create it first:" >&2
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -e \"backend[llm,dev]\"" >&2
  exit 1
fi
source "$ROOT/.venv/bin/activate"
cd "$ROOT/backend"
# this machine's Python has no system CA bundle wired up (SSL_CERT_FILE unset), so outbound HTTPS --
# including every Cartesia and Anthropic call -- fails cert verification and falls back silently
# (Cartesia TTS failing means the browser's own, much more robotic, speechSynthesis takes over).
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"
python -m seed.load
uvicorn ellis.api.app:app --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npx vite --port 5173
