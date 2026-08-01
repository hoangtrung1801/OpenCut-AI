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
LOG_TAIL_PID=""

log_info() {
    printf '\033[0;32m[INFO]\033[0m  %s\n' "$*"
}

log_error() {
    printf '\033[0;31m[ERROR]\033[0m %s\n' "$*" >&2
}

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM

    if [ -n "$LOG_TAIL_PID" ] && kill -0 "$LOG_TAIL_PID" 2>/dev/null; then
        kill "$LOG_TAIL_PID" 2>/dev/null || true
    fi

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done

    if [ "$exit_code" -ne 0 ] && [ "$exit_code" -ne 130 ] && [ "$exit_code" -ne 143 ]; then
        log_error "Service logs preserved at $LOG_DIR"
    else
        rm -rf "$LOG_DIR"
    fi
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

if ! command -v curl >/dev/null 2>&1; then
    log_error "curl is required to verify local service readiness."
    exit 1
fi

STARTUP_TIMEOUT_SECONDS="${OPENCUTAI_SERVICE_STARTUP_TIMEOUT_SECONDS:-180}"

# Keep model/device defaults local to this process. Existing shell values win.
# export CLIP_MODEL_NAME="${CLIP_MODEL_NAME:-ViT-B-32}"
# export CLIP_PRETRAINED="${CLIP_PRETRAINED:-laion2b_s34b_b79k}"
export DEVICE="${DEVICE:-${OPENCUTAI_AI_COMPUTE_MODE:-auto}}"
# export AI_PROVIDER="${AI_PROVIDER:-local}"
# export OPENAI_MODEL="${OPENAI_MODEL:-gpt-4o-mini}"
# export KV_CACHE_BITS="${KV_CACHE_BITS:-4}"
# export MAX_CONTEXT_LENGTH="${MAX_CONTEXT_LENGTH:-8192}"

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

wait_for_health() {
    local service_name="$1"
    local health_url="$2"
    local pid="$3"
    local elapsed=0

    log_info "Waiting for $service_name readiness..."
    while [ "$elapsed" -lt "$STARTUP_TIMEOUT_SECONDS" ]; do
        if ! service_is_running "$pid"; then
            log_error "$service_name exited during startup. Check $LOG_DIR/$service_name.log"
            return 1
        fi
        if curl --silent --show-error --fail --max-time 2 "$health_url" >/dev/null 2>&1; then
            log_info "$service_name is ready."
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_error "$service_name did not become ready within ${STARTUP_TIMEOUT_SECONDS}s. Check $LOG_DIR/$service_name.log"
    return 1
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

stream_logs() {
    local stream_pids=()

    cleanup_log_streams() {
        for stream_pid in "${stream_pids[@]}"; do
            if kill -0 "$stream_pid" 2>/dev/null; then
                kill "$stream_pid" 2>/dev/null || true
            fi
        done
        wait 2>/dev/null || true
    }

    trap cleanup_log_streams EXIT INT TERM

    for spec in "${SERVICE_SPECS[@]}"; do
        IFS='|' read -r service_name _port _target _health_url <<< "$spec"
        (
            tail -n +1 -f "$LOG_DIR/$service_name.log" |
                while IFS= read -r line; do
                    printf '\033[0;36m%s\033[0m %s\n' "[$service_name]" "$line"
                done
        ) &
        stream_pids+=("$!")
    done

    wait
}

log_info "Preparing six local services. AI backend and web are excluded."

for spec in "${SERVICE_SPECS[@]}"; do
    IFS='|' read -r service_name _port _target _health_url <<< "$spec"
    prepare_service "$service_name"
done

# Load the largest TTS model before starting the other model services. Starting
# all model loaders simultaneously can exhaust macOS shared memory and abort
# the TTS process with SIGBUS while its weights are memory-mapped.
start_service "tts-service" 8422 "app:app"
tts_pid="${PIDS[$((${#PIDS[@]} - 1))]}"
wait_for_health "tts-service" "http://127.0.0.1:8422/health" "$tts_pid"

for spec in "${SERVICE_SPECS[@]}"; do
    IFS='|' read -r service_name port uvicorn_target health_url <<< "$spec"
    [ "$service_name" = "tts-service" ] && continue
    start_service "$service_name" "$port" "$uvicorn_target"
    log_info "  health: $health_url"
done

echo ""
log_info "Streaming service logs below. Press Ctrl-C to stop all services."
stream_logs &
LOG_TAIL_PID="$!"

echo ""
log_info "All six local services are running."

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
