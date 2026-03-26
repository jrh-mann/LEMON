#!/bin/bash
# Dev server runner — starts backend and frontend together.
# Usage: ./dev.sh          (start all)
#        ./dev.sh restart   (kill existing, then start all)
#        ./dev.sh stop      (kill all)

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDFILE="$REPO_ROOT/.dev-pids"

stop_all() {
    if [ -f "$PIDFILE" ]; then
        while read -r pid; do
            kill "$pid" 2>/dev/null
        done < "$PIDFILE"
        rm -f "$PIDFILE"
    fi
    # Also kill by port as fallback
    for port in 5001 5173; do
        lsof -ti:"$port" 2>/dev/null | xargs kill 2>/dev/null
    done
    sleep 1
}

start_all() {
    cd "$REPO_ROOT"
    source .venv/bin/activate

    # Ensure log directory exists
    mkdir -p "$REPO_ROOT/.lemon/logs"
    LOGDIR="$REPO_ROOT/.lemon/logs"

    # Backend API — stdout/stderr go to _stdout.log; structured logs go to
    # backend.log via the app's own logging module (same directory).
    python run_api.py > "$LOGDIR/backend_stdout.log" 2>&1 &
    echo $! >> "$PIDFILE"

    # Frontend (from src/frontend)
    cd "$REPO_ROOT/src/frontend"
    npx vite --host > "$LOGDIR/frontend.log" 2>&1 &
    echo $! >> "$PIDFILE"

    sleep 2
    echo "Backend:  $(lsof -ti:5001 >/dev/null 2>&1 && echo 'UP on :5001' || echo 'FAILED')"
    echo "Frontend: $(lsof -ti:5173 >/dev/null 2>&1 && echo 'UP on :5173' || echo 'FAILED')"
}

case "${1:-start}" in
    stop)
        stop_all
        echo "All servers stopped."
        ;;
    restart)
        stop_all
        start_all
        ;;
    start)
        start_all
        ;;
esac
