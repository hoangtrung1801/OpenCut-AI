#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICES_ROOT="$PROJECT_ROOT/services"
LOG_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opencut-services.XXXXXX")"

# service-directory|port|uvicorn-target|health-url
SERVICE_SPECS=(
    "whisper-service|8421|app:app|http://127.0.0.1:8421/health"
    "tts-service|8422|app:app|http://127.0.0.1:8422/health"
    "image-service|8423|app:app|http://127.0.0.1:8423/health"
    "speaker-service|8424|app:app|http://127.0.0.1:8424/health"
    "clip-service|8426|app:app|http://127.0.0.1:8426/health"
    "turboquant-service|8430|app:app|http://127.0.0.1:8430/health"
)

PIDS=()
PID_NAMES=()

log_info() {
    printf '\033[0;32m[INFO]\033[0m  %s\n' "$*"
}

log_error() {
    printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done

    rm -rf "$LOG_DIR"
    exit "$exit_code"
}

trap cleanup EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
    log_error "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    log_error "python3 is required but was not found in PATH."
    exit 1
fi

# Keep model/device defaults local to this process. Existing shell values win.
export WHISPER_MODEL_SIZE="${WHISPER_MODEL_SIZE:-base}"
export WHISPER_DEVICE="${WHISPER_DEVICE:-cpu}"
export WHISPER_COMPUTE_TYPE="${WHISPER_COMPUTE_TYPE:-int8}"
export TTS_AUTOLOAD="${TTS_AUTOLOAD:-true}"
export CLIP_MODEL_NAME="${CLIP_MODEL_NAME:-ViT-B-32}"
export CLIP_PRETRAINED="${CLIP_PRETRAINED:-laion2b_s34b_b79k}"
export DEVICE="${DEVICE:-${OPENCUTAI_AI_COMPUTE_MODE:-auto}}"
export AI_PROVIDER="${AI_PROVIDER:-local}"
export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
export MODEL_NAME="${MODEL_NAME:-Qwen/Qwen2.5-0.5B-Instruct}"
export MODEL_DIR="${MODEL_DIR:-$SERVICES_ROOT/turboquant-service/models}"
export KV_CACHE_BITS="${KV_CACHE_BITS:-4}"
export MAX_CONTEXT_LENGTH="${MAX_CONTEXT_LENGTH:-8192}"

prepare_service() {
    local service_name="$1"
    local service_dir="$SERVICES_ROOT/$service_name"
    local venv_dir="$service_dir/.venv"
    local requirements_file="$service_dir/requirements.txt"
    local lock_file="$service_dir/requirements.lock"
    local python_path="$venv_dir/bin/python"

    if [ ! -d "$service_dir" ]; then
        log_error "Service directory does not exist: $service_dir"
        return 1
    fi

    if [ ! -x "$python_path" ]; then
        log_info "Creating virtual environment for $service_name"
        uv venv "$venv_dir" --python 3.11
    fi

    if [ -f "$lock_file" ]; then
        requirements_file="$lock_file"
    fi

    if [ ! -f "$requirements_file" ]; then
        log_error "No dependency file found for $service_name"
        return 1
    fi

    log_info "Installing dependencies for $service_name from $(basename "$requirements_file")"
    uv pip install --python "$python_path" -r "$requirements_file"
}

start_service() {
    local service_name="$1"
    local port="$2"
    local uvicorn_target="$3"
    local service_dir="$SERVICES_ROOT/$service_name"
    local venv_dir="$service_dir/.venv"
    local log_file="$LOG_DIR/$service_name.log"

    log_info "Starting $service_name on http://127.0.0.1:$port"
    (
        cd "$service_dir"
        exec "$venv_dir/bin/uvicorn" "$uvicorn_target" \
            --host 127.0.0.1 \
            --port "$port"
    ) >"$log_file" 2>&1 &

    PIDS+=("$!")
    PID_NAMES+=("$service_name")
    log_info "  logs: $log_file"
}

service_is_running() {
    local pid="$1"
    local process_state

    if ! kill -0 "$pid" 2>/dev/null; then
        return 1
    fi

    process_state="$(ps -o stat= -p "$pid" 2>/dev/null | tr -d '[:space:]')"
    case "$process_state" in
        ""|Z*) return 1 ;;
    esac
}

log_info "Preparing six local services. AI backend and web are excluded."

for spec in "${SERVICE_SPECS[@]}"; do
    IFS='|' read -r service_name _port _target _health_url <<< "$spec"
    prepare_service "$service_name"
done

for spec in "${SERVICE_SPECS[@]}"; do
    IFS='|' read -r service_name port uvicorn_target health_url <<< "$spec"
    start_service "$service_name" "$port" "$uvicorn_target"
    log_info "  health: $health_url"
done

echo ""
log_info "All six local services are running. Press Ctrl-C to stop them."

while true; do
    for index in "${!PIDS[@]}"; do
        pid="${PIDS[$index]}"
        if ! service_is_running "$pid"; then
            service_name="${PID_NAMES[$index]}"
            log_error "$service_name exited unexpectedly. Check $LOG_DIR/$service_name.log"
            exit 1
        fi
    done
    sleep 1
done
