#!/usr/bin/env bash
# One command for local dev: seed the synthetic demo, run the Case API (+ in-process agent runner) and the web app.
#   ./scripts/dev.sh            # uses backend/.env (DATABASE_URL defaults to SQLite if unset)
# Python always runs from the repo-root .venv. If it doesn't exist yet, this script creates it and installs
# the backend into it (pip install -e "backend[llm,dev]"); nothing is installed outside .venv.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ELLIS_TODAY="${ELLIS_TODAY:-2026-10-23}"   # the flows are written for Fri Oct 23, 2026
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  PY="${PYTHON:-python3}"
  if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    echo "Ellis needs Python 3.12+ to create $ROOT/.venv (set PYTHON=/path/to/python3.12+)." >&2
    exit 1
  fi
  echo "Creating virtualenv at $ROOT/.venv ..."
  "$PY" -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/python" -m pip install --upgrade pip
  "$ROOT/.venv/bin/python" -m pip install -e "$ROOT/backend[llm,dev]"
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
