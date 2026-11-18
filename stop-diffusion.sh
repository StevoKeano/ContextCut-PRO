#!/bin/bash
INST="$(dirname "$0")"
PIDFILE="$INST/.diffusion.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "Diffusion worker is not running (no PID file)."
  exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
  echo "Stopping diffusion worker (PID $PID)..."
  kill "$PID"
  sleep 1
  echo "Diffusion worker stopped."
else
  echo "Diffusion worker PID $PID is not running."
fi
rm -f "$PIDFILE"
