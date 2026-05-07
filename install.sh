#!/bin/bash
# ContextCut installer — macOS / Linux
# https://github.com/StevoKeano/ContextCut

REPO="https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main"
INSTALL_DIR="$HOME/contextcut"
LOG_DIR="$HOME/.contextcut/logs"
PLIST_PROXY="$HOME/Library/LaunchAgents/ai.contextcut.proxy.plist"
PLIST_INGEST="$HOME/Library/LaunchAgents/ai.contextcut.ingest.plist"
IS_MAC=false
[ "$(uname)" = "Darwin" ] && IS_MAC=true

echo ""
echo "  ContextCut installer"
echo "  Stop wasting tokens. Inject only what matters."
echo "  ──────────────────────────────────────────────"
echo ""

# ── Detect auto-install mode (key pre-set by piped URL) ──────────────────────
AUTO_INSTALL=false
if [ -n "$CONTEXTCUT_LICENSE_KEY" ]; then
  AUTO_INSTALL=true
  LICENSE_KEY="$CONTEXTCUT_LICENSE_KEY"
  echo ""
  echo "  ── ContextCut PRO License ──"
  echo "  License key detected automatically: ${LICENSE_KEY:0:16}..."
fi

# ── Collect config ────────────────────────────────────────────────────────────
if $AUTO_INSTALL; then
  echo ""
  echo "  ── Configuration ──"
  echo "  Defaults shown in [brackets]. Press Enter to accept, or type a new value."
  echo ""

  read -p "  Voyage AI API key (leave blank for local Ollama embedding): " VOYAGE_KEY

  if [ -z "$VOYAGE_KEY" ]; then
    echo "  100% local mode — using Ollama for embeddings."
    read -p "  Embedding model [nomic-embed-text]: " EMBED_MODEL
    EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
  fi

  read -p "  Ollama host [localhost]: " OLLAMA_HOST
  OLLAMA_HOST="${OLLAMA_HOST:-localhost}"

  read -p "  Ollama port [11434]: " OLLAMA_PORT
  OLLAMA_PORT="${OLLAMA_PORT:-11434}"

  read -p "  Qdrant host [localhost]: " QDRANT_HOST
  QDRANT_HOST="${QDRANT_HOST:-localhost}"

  read -p "  Qdrant port [6333]: " QDRANT_PORT
  QDRANT_PORT="${QDRANT_PORT:-6333}"

  read -p "  Knowledge base dir [$INSTALL_DIR/knowledge]: " KB_DIR
  KB_DIR="${KB_DIR:-$INSTALL_DIR/knowledge}"

  read -p "  Proxy port [18788]: " PROXY_PORT
  PROXY_PORT="${PROXY_PORT:-18788}"

  read -p "  Dashboard port [18787]: " DASH_PORT
  DASH_PORT="${DASH_PORT:-18787}"

  read -p "  Model context limit [8192]: " CTX_LIMIT
  CTX_LIMIT="${CTX_LIMIT:-8192}"

  read -p "  Minimum relevance score 0.0-1.0 [0.20]: " MIN_SCORE
  MIN_SCORE="${MIN_SCORE:-0.20}"

  echo ""
  echo "  ── Confirm Your Settings ──"
  echo "  License key : ${LICENSE_KEY:0:16}..."
  echo "  Voyage API  : ${VOYAGE_KEY:0:8}..."
  echo "  Ollama      : $OLLAMA_HOST:$OLLAMA_PORT"
  echo "  Qdrant      : $QDRANT_HOST:$QDRANT_PORT"
  echo "  KB dir      : $KB_DIR"
  echo "  Proxy       : http://localhost:$PROXY_PORT"
  echo "  Dashboard   : http://localhost:$DASH_PORT"
  echo "  CTX limit   : $CTX_LIMIT"
  echo "  Min score   : $MIN_SCORE"
  echo ""
  read -p "  Proceed with these settings? [Y/n]: " CONFIRM
  if [ "$CONFIRM" = "n" ] || [ "$CONFIRM" = "N" ]; then
    echo "  Installation cancelled."
    exit 1
  fi
else
  echo ""
  echo "  ── ContextCut PRO License ──"
  echo "  Your license key was sent to your email after purchase on Gumroad."
  echo "  It looks like: CC-PRO-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  echo ""
  read -p "  PRO License key: " LICENSE_KEY
  if [ -z "$LICENSE_KEY" ]; then
    echo "ERROR: License key is required. Purchase at https://5984630877416.gumroad.com/l/ContextCut-Pro"
    exit 1
  fi

  read -p "  Voyage AI API key (from dash.voyageai.com): " VOYAGE_KEY
  if [ -z "$VOYAGE_KEY" ]; then
    echo "ERROR: Voyage API key is required."
    exit 1
  fi

  read -p "  Ollama host [localhost]: " OLLAMA_HOST
  OLLAMA_HOST="${OLLAMA_HOST:-localhost}"

  read -p "  Ollama port [11434]: " OLLAMA_PORT
  OLLAMA_PORT="${OLLAMA_PORT:-11434}"

  read -p "  Qdrant host [localhost]: " QDRANT_HOST
  QDRANT_HOST="${QDRANT_HOST:-localhost}"

  read -p "  Qdrant port [6333]: " QDRANT_PORT
  QDRANT_PORT="${QDRANT_PORT:-6333}"

  read -p "  Knowledge base dir [$INSTALL_DIR/knowledge]: " KB_DIR
  KB_DIR="${KB_DIR:-$INSTALL_DIR/knowledge}"

  read -p "  Proxy port [18788]: " PROXY_PORT
  PROXY_PORT="${PROXY_PORT:-18788}"

  read -p "  Dashboard port [18787]: " DASH_PORT
  DASH_PORT="${DASH_PORT:-18787}"

  read -p "  Model context limit [8192]: " CTX_LIMIT
  CTX_LIMIT="${CTX_LIMIT:-8192}"

  read -p "  Minimum relevance score 0.0-1.0 [0.20]: " MIN_SCORE
  MIN_SCORE="${MIN_SCORE:-0.20}"
fi

echo ""
echo "  Installing to $INSTALL_DIR ..."

# ── Create directories ────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR" "$LOG_DIR" "$KB_DIR"

# ── Check Qdrant ──────────────────────────────────────────────────────────────
echo "  Checking Qdrant at $QDRANT_HOST:$QDRANT_PORT ..."
if curl -sf "http://$QDRANT_HOST:$QDRANT_PORT/collections" > /dev/null 2>&1; then
  echo "  Qdrant found."
else
  echo ""
  echo "  Qdrant not reachable at $QDRANT_HOST:$QDRANT_PORT"
  if command -v docker &>/dev/null; then
    read -p "  Start Qdrant via Docker now? [y/N]: " START_QDRANT
    if [ "$START_QDRANT" = "y" ] || [ "$START_QDRANT" = "Y" ]; then
      docker run -d --name qdrant --restart always \
        -p "$QDRANT_PORT:6333" \
        -v "$INSTALL_DIR/qdrant_storage:/qdrant/storage" \
        qdrant/qdrant
      echo "  Qdrant started. Waiting 5s..."
      sleep 5
    fi
  else
    echo "  Docker not found. Install Qdrant manually:"
    echo "    https://qdrant.tech/documentation/quick-start/"
    echo "  Or install Docker Desktop: https://docker.com"
    exit 1
  fi
fi

# ── Python venv ───────────────────────────────────────────────────────────────
echo "  Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

echo "  Installing Python dependencies..."
pip install --upgrade pip -q
pip install voyageai qdrant-client watchdog cryptography -q
pip install tiktoken -q && echo "  tiktoken installed (exact token counts)" || echo "  tiktoken skipped (estimate mode)"

# ── Download scripts ──────────────────────────────────────────────────────────
echo "  Downloading ContextCut scripts..."
curl -sf "$REPO/qdrant_proxy_final.py" -o "$INSTALL_DIR/qdrant_proxy_final.py"
curl -sf "$REPO/ingest.py"       -o "$INSTALL_DIR/ingest.py"

# ── Write env file ────────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/.env" << EOF
CONTEXTCUT_LICENSE_KEY=$LICENSE_KEY
CONTEXTCUT_LICENSE_SERVER=https://contextcut-license.ppsel03.workers.dev
VOYAGE_API_KEY=$VOYAGE_KEY
CONTEXTCUT_EMBED_MODEL=$EMBED_MODEL
CONTEXTCUT_UPSTREAM=http://$OLLAMA_HOST:$OLLAMA_PORT
CONTEXTCUT_QDRANT_HOST=$QDRANT_HOST
CONTEXTCUT_QDRANT_PORT=$QDRANT_PORT
CONTEXTCUT_KB_DIR=$KB_DIR
CONTEXTCUT_PROXY_PORT=$PROXY_PORT
CONTEXTCUT_DASHBOARD_PORT=$DASH_PORT
CONTEXTCUT_CTX_LIMIT=$CTX_LIMIT
CONTEXTCUT_MIN_SCORE=$MIN_SCORE
CONTEXTCUT_COLLECTION=contextcut
EOF
chmod 600 "$INSTALL_DIR/.env"

# ── macOS launchd ─────────────────────────────────────────────────────────────
if $IS_MAC; then

  cat > "$INSTALL_DIR/reset_license.sh" << 'RESETEOF'
#!/bin/bash
ENV_FILE="$(dirname "$0")/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi
KEY=$(grep "^CONTEXTCUT_LICENSE_KEY=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
if [ -z "$KEY" ]; then
  echo "ERROR: No license key found in .env"
  exit 1
fi
echo "Resetting license: ${KEY:0:16}..."
RESULT=$(curl -sf -X POST "https://contextcut-license.ppsel03.workers.dev/v1/license/reset" \
  -H "Content-Type: application/json" \
  -d "{\"license_key\": \"${KEY}\"}")
if [ $? -eq 0 ] && echo "$RESULT" | grep -q '"valid"'; then
  echo "License seats reset successfully."
  echo "Restart:  launchctl kickstart gui/$(id -u)/ai.contextcut.proxy"
else
  echo "Reset failed. Try again or contact support."
  echo "Response: $RESULT"
fi
RESETEOF
  chmod +x "$INSTALL_DIR/reset_license.sh"

  echo "  Installing launchd agents..."

  cat > "$PLIST_PROXY" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.contextcut.proxy</string>
  <key>Comment</key><string>ContextCut Qdrant Proxy + Dashboard</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/venv/bin/python</string>
    <string>$INSTALL_DIR/qdrant_proxy_final.py</string>
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/proxy.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/proxy.err.log</string>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>CONTEXTCUT_LICENSE_KEY</key><string>$LICENSE_KEY</string>
    <key>CONTEXTCUT_LICENSE_SERVER</key><string>https://contextcut-license.ppsel03.workers.dev</string>
    <key>VOYAGE_API_KEY</key><string>$VOYAGE_KEY</string>
    <key>CONTEXTCUT_EMBED_MODEL</key><string>$EMBED_MODEL</string>
    <key>CONTEXTCUT_UPSTREAM</key><string>http://$OLLAMA_HOST:$OLLAMA_PORT</string>
    <key>CONTEXTCUT_QDRANT_HOST</key><string>$QDRANT_HOST</string>
    <key>CONTEXTCUT_QDRANT_PORT</key><string>$QDRANT_PORT</string>
    <key>CONTEXTCUT_PROXY_PORT</key><string>$PROXY_PORT</string>
    <key>CONTEXTCUT_DASHBOARD_PORT</key><string>$DASH_PORT</string>
    <key>CONTEXTCUT_CTX_LIMIT</key><string>$CTX_LIMIT</string>
    <key>CONTEXTCUT_MIN_SCORE</key><string>$MIN_SCORE</string>
    <key>CONTEXTCUT_COLLECTION</key><string>contextcut</string>
  </dict>
</dict>
</plist>
EOF

  cat > "$PLIST_INGEST" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.contextcut.ingest</string>
  <key>Comment</key><string>ContextCut Knowledge Base Watcher</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/venv/bin/python</string>
    <string>$INSTALL_DIR/ingest.py</string>
    <string>--watch</string>
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/ingest.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/ingest.err.log</string>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>VOYAGE_API_KEY</key><string>$VOYAGE_KEY</string>
    <key>CONTEXTCUT_QDRANT_HOST</key><string>$QDRANT_HOST</string>
    <key>CONTEXTCUT_QDRANT_PORT</key><string>$QDRANT_PORT</string>
    <key>CONTEXTCUT_KB_DIR</key><string>$KB_DIR</string>
    <key>CONTEXTCUT_COLLECTION</key><string>contextcut</string>
  </dict>
</dict>
</plist>
EOF

  plutil -lint "$PLIST_PROXY"  > /dev/null && echo "  Proxy plist OK"
  plutil -lint "$PLIST_INGEST" > /dev/null && echo "  Ingest plist OK"

  launchctl bootstrap gui/$(id -u) "$PLIST_PROXY"
  launchctl bootstrap gui/$(id -u) "$PLIST_INGEST"
  echo "  launchd agents started."

else
  # Linux — write start/stop scripts
  cat > "$INSTALL_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
set -a
source "$(dirname "$0")/.env"
set +a

INST="$(dirname "$0")"

# ── Start watcher ──
WATCHER_PIDFILE="$INST/.ingest.pid"
if [ -f "$WATCHER_PIDFILE" ] && kill -0 $(cat "$WATCHER_PIDFILE") 2>/dev/null; then
  echo "Watcher already running (PID $(cat "$WATCHER_PIDFILE"))."
else
  "$INST/venv/bin/python" "$INST/ingest.py" --watch &
  echo $! > "$WATCHER_PIDFILE"
  echo "Watcher started. PID: $(cat "$WATCHER_PIDFILE")"
fi

# ── Start proxy ──
PROXY_PIDFILE="$INST/.proxy.pid"
if [ -f "$PROXY_PIDFILE" ] && kill -0 $(cat "$PROXY_PIDFILE") 2>/dev/null; then
  echo "Proxy already running (PID $(cat "$PROXY_PIDFILE")). Stop it first with ./stop.sh"
  exit 1
fi
source "$INST/.env"
"$INST/venv/bin/python" "$INST/qdrant_proxy_final.py" &
echo $! > "$PROXY_PIDFILE"
echo "ContextCut started. Dashboard: http://localhost:${CONTEXTCUT_DASHBOARD_PORT}"
STARTEOF
  chmod +x "$INSTALL_DIR/start.sh"

  cat > "$INSTALL_DIR/stop.sh" << 'STOPEOF'
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
else
  echo "No PID files found. Attempting pkill..."
  pkill -f ingest.py 2>/dev/null
  pkill -f qdrant_proxy_final.py 2>/dev/null
  sleep 1
fi
echo "Done."
STOPEOF
  chmod +x "$INSTALL_DIR/stop.sh"

  cat > "$INSTALL_DIR/reset_license.sh" << 'RESETEOF'
#!/bin/bash
ENV_FILE="$(dirname "$0")/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env not found at $ENV_FILE"
  exit 1
fi
KEY=$(grep "^CONTEXTCUT_LICENSE_KEY=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'")
if [ -z "$KEY" ]; then
  echo "ERROR: No license key found in .env"
  exit 1
fi
echo "Resetting license: ${KEY:0:16}..."
RESULT=$(curl -sf -X POST "https://contextcut-license.ppsel03.workers.dev/v1/license/reset" \
  -H "Content-Type: application/json" \
  -d "{\"license_key\": \"${KEY}\"}")
if [ $? -eq 0 ] && echo "$RESULT" | grep -q '"valid"'; then
  echo "License seats reset successfully."
  echo "Restart proxy:  ./start.sh"
else
  echo "Reset failed. Try again or contact support."
  echo "Response: $RESULT"
fi
RESETEOF
  chmod +x "$INSTALL_DIR/reset_license.sh"

  echo "  Linux: starting services now..."
  bash "$INSTALL_DIR/start.sh"
fi

# ── Initial ingest ────────────────────────────────────────────────────────────
echo ""
echo "  Running initial knowledge base ingest..."
echo "  (this may take a while — Voyage AI free tier: 1 file per 21s)"
echo ""
export VOYAGE_API_KEY="$VOYAGE_KEY"
export CONTEXTCUT_QDRANT_HOST="$QDRANT_HOST"
export CONTEXTCUT_QDRANT_PORT="$QDRANT_PORT"
export CONTEXTCUT_KB_DIR="$KB_DIR"
export CONTEXTCUT_COLLECTION="contextcut"
"$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/ingest.py" || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ContextCut installed successfully!"
echo ""
echo "  Dashboard:  http://localhost:$DASH_PORT"
echo "  Proxy:      http://localhost:$PROXY_PORT"
echo "  KB dir:     $KB_DIR"
echo "  Logs:       $LOG_DIR"
echo ""
echo "  Test it:"
echo "    curl -X POST http://localhost:$PROXY_PORT/v1/chat/completions \\"
echo "      -H 'Content-Type: application/json' \\"
echo "      -d '{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"model\":\"your-model-name\"}'"
echo ""
echo "  Add .md files to $KB_DIR and they will be auto-ingested."
echo ""
