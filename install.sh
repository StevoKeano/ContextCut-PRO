#!/bin/bash
# ContextCut installer — macOS / Linux
# https://github.com/StevoKeano/ContextCut
set -e

REPO="https://raw.githubusercontent.com/StevoKeano/ContextCut/main"
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

# ── Collect config ────────────────────────────────────────────────────────────
read -p "Voyage AI API key (from dash.voyageai.com): " VOYAGE_KEY
if [ -z "$VOYAGE_KEY" ]; then
  echo "ERROR: Voyage API key is required."
  exit 1
fi

read -p "Ollama host [localhost]: " OLLAMA_HOST
OLLAMA_HOST="${OLLAMA_HOST:-localhost}"

read -p "Ollama port [11434]: " OLLAMA_PORT
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

read -p "Qdrant host [localhost]: " QDRANT_HOST
QDRANT_HOST="${QDRANT_HOST:-localhost}"

read -p "Qdrant port [6333]: " QDRANT_PORT
QDRANT_PORT="${QDRANT_PORT:-6333}"

read -p "Path to your markdown knowledge base [$INSTALL_DIR/knowledge]: " KB_DIR
KB_DIR="${KB_DIR:-$INSTALL_DIR/knowledge}"

read -p "Proxy port [18788]: " PROXY_PORT
PROXY_PORT="${PROXY_PORT:-18788}"

read -p "Dashboard port [18787]: " DASH_PORT
DASH_PORT="${DASH_PORT:-18787}"

read -p "Model context limit [8192]: " CTX_LIMIT
CTX_LIMIT="${CTX_LIMIT:-8192}"

read -p "Minimum relevance score 0.0-1.0 [0.30]: " MIN_SCORE
MIN_SCORE="${MIN_SCORE:-0.30}"

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
pip install voyageai qdrant-client watchdog -q
pip install tiktoken -q && echo "  tiktoken installed (exact token counts)" || echo "  tiktoken skipped (estimate mode)"

# ── Download scripts ──────────────────────────────────────────────────────────
echo "  Downloading ContextCut scripts..."
curl -sf "$REPO/qdrant_proxy.py" -o "$INSTALL_DIR/qdrant_proxy.py"
curl -sf "$REPO/ingest.py"       -o "$INSTALL_DIR/ingest.py"

# ── Write env file ────────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/.env" << EOF
VOYAGE_API_KEY=$VOYAGE_KEY
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
    <string>$INSTALL_DIR/qdrant_proxy.py</string>
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/proxy.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/proxy.err.log</string>
  <key>WorkingDirectory</key><string>$INSTALL_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>PATH</key><string>$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>VOYAGE_API_KEY</key><string>$VOYAGE_KEY</string>
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
  # Linux — write systemd units or simple launch script
  cat > "$INSTALL_DIR/start.sh" << EOF
#!/bin/bash
source $INSTALL_DIR/.env
export \$(cat $INSTALL_DIR/.env | xargs)
$INSTALL_DIR/venv/bin/python $INSTALL_DIR/qdrant_proxy.py &
echo "ContextCut started. Dashboard: http://localhost:$DASH_PORT"
EOF
  chmod +x "$INSTALL_DIR/start.sh"
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
