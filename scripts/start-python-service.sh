#!/usr/bin/env bash

set -Eeuo pipefail

if [ "$#" -ne 2 ]; then
    printf 'Usage: %s <service-name> <port>\n' "$0" >&2
    exit 64
fi

SERVICE_NAME="$1"
PORT="$2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_DIR="$PROJECT_ROOT/services/$SERVICE_NAME"
VENV_DIR="$SERVICE_DIR/.venv"
PYTHON_PATH="$VENV_DIR/bin/python"

if ! [[ "$SERVICE_NAME" =~ ^[a-z0-9-]+$ ]]; then
    printf '[ERROR] Invalid service name: %s\n' "$SERVICE_NAME" >&2
    exit 64
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
    printf '[ERROR] Invalid port: %s\n' "$PORT" >&2
    exit 64
fi

if [ ! -d "$SERVICE_DIR" ]; then
    printf '[ERROR] Service directory does not exist: %s\n' "$SERVICE_DIR" >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    printf '[ERROR] uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/\n' >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf '[ERROR] python3 was not found in PATH.\n' >&2
    exit 1
fi

if [ ! -x "$PYTHON_PATH" ]; then
    echo "[INFO] Creating virtual environment for $SERVICE_NAME"
    uv venv "$VENV_DIR" --python 3.11
fi

REQUIREMENTS_FILE="$SERVICE_DIR/requirements.txt"
if [ -f "$SERVICE_DIR/requirements.lock" ]; then
    REQUIREMENTS_FILE="$SERVICE_DIR/requirements.lock"
fi

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    printf '[ERROR] No dependency file found for %s\n' "$SERVICE_NAME" >&2
    exit 1
fi

echo "[INFO] Installing $SERVICE_NAME dependencies from $(basename "$REQUIREMENTS_FILE")"
uv pip install --python "$PYTHON_PATH" -r "$REQUIREMENTS_FILE"

echo "[INFO] Starting $SERVICE_NAME at http://127.0.0.1:$PORT"
cd "$SERVICE_DIR"
exec "$VENV_DIR/bin/uvicorn" app:app --host 127.0.0.1 --port "$PORT"
