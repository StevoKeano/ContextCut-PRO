#!/bin/bash
INST="$(dirname "$0")"

# Stop watcher
WATCHER_PIDFILE="$INST/.ingest.pid"
if [ -f "$WATCHER_PIDFILE" ]; then
  PID=$(cat "$WATCHER_PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping watcher (PID $PID)..."
    kill "$PID"
    echo "Watcher stopped."
  fi
  rm -f "$WATCHER_PIDFILE"
fi

# Release license seat before stopping proxy
ENV_FILE="$INST/.env"
SECRET_FILE="$HOME/.contextcut/instance_secret"
if [ -f "$ENV_FILE" ] && [ -f "$SECRET_FILE" ]; then
  KEY=$(grep "^CONTEXTCUT_LICENSE_KEY=" "$ENV_FILE" | sed 's/^[^=]*=//; s/^["'\'']//; s/["'\'']$//')
  INSTANCE_ID=$(grep "^CONTEXTCUT_INSTANCE_ID=" "$ENV_FILE" | sed 's/^[^=]*=//; s/^["'\'']//; s/["'\'']$//')
  SECRET=$(cat "$SECRET_FILE")
  if [ -n "$KEY" ] && [ -n "$INSTANCE_ID" ] && [ -n "$SECRET" ]; then
    echo "Releasing license seat..."
    curl -sf -X POST 'https://api.contextcut-pro.com/v1/license/release' \
      -H 'Content-Type: application/json' \
      -d '{"license_key":"'"$KEY"'","instance_id":"'"$INSTANCE_ID"'","instance_secret":"'"$SECRET"'"}' \
      > /dev/null 2>&1 && echo "Seat released." || echo "Release failed (seat expires in 30 min)."
  fi
fi

# Stop MCP knowledge server
MCP_PIDFILE="$INST/.mcp.pid"
if [ -f "$MCP_PIDFILE" ]; then
  PID=$(cat "$MCP_PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping MCP server (PID $PID)..."
    kill "$PID"
    echo "MCP server stopped."
  fi
  rm -f "$MCP_PIDFILE"
fi

# Stop proxy
PROXY_PIDFILE="$INST/.proxy.pid"
if [ -f "$PROXY_PIDFILE" ]; then
  PID=$(cat "$PROXY_PIDFILE")
  if kill -0 "$PID" 2>/dev/null; then
    echo "Stopping proxy (PID $PID)..."
    kill "$PID"
    sleep 1
    echo "Proxy stopped."
  fi
  rm -f "$PROXY_PIDFILE"
  rm -f "$INST/.proxy_ready"
fi
