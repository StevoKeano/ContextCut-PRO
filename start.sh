#!/bin/bash
INST="$(dirname "$0")"

# Clean stale ready file
rm -f "$INST/.proxy_ready"

# ââ Start proxy first (it ensures correct collection dimension) ââ
PROXY_PIDFILE="$INST/.proxy.pid"
if [ -f "$PROXY_PIDFILE" ] && kill -0 $(cat "$PROXY_PIDFILE") 2>/dev/null; then
  echo "Proxy already running (PID $(cat "$PROXY_PIDFILE")). Stop it first with ./stop.sh"
  exit 1
fi
# Source env for proxy (uses pre-existing values; proxy will sync .env after starting)
# Source and export env for proxy (proxy reads from os.environ)
set -a
source "$INST/.env"
set +a
"$INST/venv/bin/python" "$INST/qdrant_proxy_final.py" &
echo $! > "$PROXY_PIDFILE"

# Wait for proxy ready marker (means .env synced + collection fixed)
echo "Waiting for proxy to initialize..."
for i in $(seq 1 60); do
  if [ -f "$INST/.proxy_ready" ]; then
    echo "Proxy ready."
    break
  fi
  sleep 1
done

# Re-source .env after proxy syncs it, then export so ingest gets correct settings
set -a
source "$INST/.env"
set +a

# ---- Start MCP knowledge server ----
MCP_PORT="${CONTEXTCUT_MCP_PORT:-8910}"
MCP_PIDFILE="$INST/.mcp.pid"
if [ -f "$MCP_PIDFILE" ] && kill -0 $(cat "$MCP_PIDFILE") 2>/dev/null; then
  echo "MCP server already running (PID $(cat "$MCP_PIDFILE"))."
else
  "$INST/venv/bin/python" "$INST/mcp_knowledge_server.py" --transport http --port "$MCP_PORT" &
  echo $! > "$MCP_PIDFILE"
  echo "MCP server started (PID $(cat "$MCP_PIDFILE")) on port $MCP_PORT."
fi

# ââ Start watcher ââ
WATCHER_PIDFILE="$INST/.ingest.pid"
if [ -f "$WATCHER_PIDFILE" ] && kill -0 $(cat "$WATCHER_PIDFILE") 2>/dev/null; then
  echo "Watcher already running (PID $(cat "$WATCHER_PIDFILE"))."
else
  "$INST/venv/bin/python" "$INST/ingest.py" --watch &
  echo $! > "$WATCHER_PIDFILE"
  echo "Watcher started. PID: $(cat "$WATCHER_PIDFILE")"
fi
echo "ContextCut started. Dashboard: http://localhost:${CONTEXTCUT_DASHBOARD_PORT}"
