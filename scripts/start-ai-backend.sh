#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$PROJECT_ROOT/services/ai-backend"
VENV_DIR="$SERVICE_DIR/.venv"
PYTHON_PATH="$VENV_DIR/bin/python"
REQUIREMENTS_FILE="$SERVICE_DIR/requirements.txt"

if ! command -v uv >/dev/null 2>&1; then
    printf '\033[0;31m[ERROR]\033[0m uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/\n' >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf '\033[0;31m[ERROR]\033[0m python3 is required but was not found in PATH.\n' >&2
    exit 1
fi

if [ ! -x "$PYTHON_PATH" ]; then
    echo "[INFO] Creating AI backend virtual environment"
    uv venv "$VENV_DIR" --python 3.11
fi

if [ -f "$SERVICE_DIR/requirements.lock" ]; then
    REQUIREMENTS_FILE="$SERVICE_DIR/requirements.lock"
fi

echo "[INFO] Installing AI backend dependencies from $(basename "$REQUIREMENTS_FILE")"
uv pip install --python "$PYTHON_PATH" -r "$REQUIREMENTS_FILE"

# Local defaults can still be overridden by the caller's environment.
export OPENCUTAI_HOST="${OPENCUTAI_HOST:-127.0.0.1}"
export OPENCUTAI_PORT="${OPENCUTAI_PORT:-8420}"

echo "[INFO] Starting AI backend at http://$OPENCUTAI_HOST:$OPENCUTAI_PORT"
cd "$SERVICE_DIR"
exec "$PYTHON_PATH" run.py
