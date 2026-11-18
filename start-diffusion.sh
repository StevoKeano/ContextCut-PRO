#!/bin/bash
INST="$(dirname "$0")"
VENV="$INST/diffusion-venv"
PIDFILE="$INST/.diffusion.pid"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Diffusion venv not found at $VENV. Run ./install-diffusion.sh first."
  exit 1
fi

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Diffusion worker already running (PID $(cat "$PIDFILE"))."
  exit 0
fi

set -a
if [ -f "$INST/.env" ]; then
  source "$INST/.env"
fi
set +a

PORT="${DIFFUSION_PORT:-8189}"
mkdir -p "$INST/outputs/images"
cd "$INST" || exit 1
"$VENV/bin/python" "$INST/diffusion/worker.py" >> "$INST/diffusion_worker.log" 2>&1 &
echo $! > "$PIDFILE"
echo "Diffusion worker starting (PID $(cat "$PIDFILE")), health: http://127.0.0.1:$PORT/health"

READY=0
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

if [ "$READY" -eq 1 ]; then
  echo "Diffusion worker ready."
else
  echo "Diffusion worker did not become ready; check $INST/diffusion_worker.log"
  exit 1
fi
