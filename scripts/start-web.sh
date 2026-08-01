#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WEB_DIR="$PROJECT_ROOT/apps/web"

if ! command -v bun >/dev/null 2>&1; then
    printf '\033[0;31m[ERROR]\033[0m bun is required. Install it from https://bun.sh/\n' >&2
    exit 1
fi

if [ ! -d "$PROJECT_ROOT/node_modules" ]; then
    echo "[INFO] Installing web dependencies"
    cd "$PROJECT_ROOT"
    bun install
fi

if [ ! -f "$WEB_DIR/.env.local" ]; then
    printf '\033[0;31m[ERROR]\033[0m Missing apps/web/.env.local. Copy apps/web/.env.example to .env.local first.\n' >&2
    exit 1
fi

WEB_PORT="${PORT:-3000}"
echo "[INFO] Starting web app at http://127.0.0.1:$WEB_PORT"
cd "$WEB_DIR"
exec bun run dev -- --hostname 127.0.0.1 --port "$WEB_PORT"
