#!/bin/bash
# ContextCut installer — macOS / Linux
# https://github.com/StevoKeano/ContextCut
set -e

REPO="https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main"
INSTALL_DIR="$HOME/contextcut"
LOG_DIR="$HOME/.contextcut/logs"
PLIST_PROXY="$HOME/Library/LaunchAgents/ai.contextcut.proxy.plist"
PLIST_INGEST="$HOME/Library/LaunchAgents/ai.contextcut.ingest.plist"
IS_MAC=false
[ "$(uname)" = "Darwin" ] && IS_MAC=true
# Print the big ASCII art
echo "________/\\\\\\\\\\\\\\\\\\_____________________________________________________________________________________________/\\\\\\\\\\\\\\\\\\_____________________________"
echo " _____/\\\\\\////////___________________________________________________________________________________________/\\\\\\////////______________________________"
echo "  ___/\\\\\\/___________________________________________/\\\\\\_______________________________________/\\\\\\________/\\\\\\/_____________________________/\\\\\\______"
echo "   __/\\\\\\_________________/\\\\\\\\\\_____/\\\\/\\\\\\\\\\\\____/\\\\\\\\\\\\\\\\\\\\\\_____/\\\\\\\\\\\\\\\\___/\\\\\\____/\\\\\\__/\\\\\\\\\\\\\\\\\\\\\\__/\\\\\\______________/\\\\\\____/\\\\\\__/\\\\\\\\\\\\\\\\\\\\\\_"
echo "    _\\/\\\\\\_______________/\\\\\\///\\\\\\__\\/\\\\\\////\\\\\\__\\////\\\\\\////____/\\\\\\/////\\\\\\_\\///\\\\\\/\\\\\\/__\\////\\\\\\////__\\/\\\\\\_____________\\/\\\\\\___\\/\\\\\\_\\////\\\\\\////__"
echo "     _\\//\\\\\\_____________/\\\\\\__\\//\\\\\\_\\/\\\\\\__\\//\\\\\\____\\/\\\\\\_______/\\\\\\\\\\\\\\\\\\\\\\____\\///\\\\\\/_______\\/\\\\\\______\\//\\\\\\____________\\/\\\\\\___\\/\\\\\\____\\/\\\\\\______"
echo "      __\\///\\\\\\__________\\//\\\\\\__/\\\\\\__\\/\\\\\\___\\/\\\\\\____\\/\\\\\\_/\\\\__\\//\\\\///////______/\\\\\\/\\\\\\______\\/\\\\\\_/\\\\___\\///\\\\\\__________\\/\\\\\\___\\/\\\\\\____\\/\\\\\\_/\\\\__"
echo "       ____\\////\\\\\\\\\\\\\\\\\\__\\///\\\\\\\\\\/___\\/\\\\\\___\\/\\\\\\____\\//\\\\\\\\\\____\\//\\\\\\\\\\\\\\\\\\\\__/\\\\\\/\\///\\\\\\____\\//\\\\\\\\\\______\\////\\\\\\\\\\\\\\\\\\_\\//\\\\\\\\\\\\\\\\\\_____\\//\\\\\\\\\\___"
echo "        _______\\/////////_____\\/////_____\\///____\\///______\\/////______\\//////////__\\///____\\///______\\/////__________\\/////////___\\/////////_______\\/////____"
# Wait 3 seconds
sleep 2

# Move cursor up and clear all the lines (11 lines total)
printf '\033[11A'          # Move cursor up 11 lines
printf '\033[0J'           # Clear from cursor to end of screen (removes the art)
echo ""
echo "  ContextCut installer"
echo "  Stop wasting tokens. Inject only what matters."
echo "  ──────────────────────────────────────────────"
echo ""


# ── Collect config ────────────────────────────────────────────────────────────

# License key from piped install URL?
if [ -n "$CONTEXTCUT_LICENSE_KEY" ]; then
  LICENSE_KEY="$CONTEXTCUT_LICENSE_KEY"
  echo ""
  echo "  ── ContextCut PRO License ──"
  echo "  License key detected automatically."
  echo "  Key: ${LICENSE_KEY:0:16}..."
else
  echo ""
  echo "  ── ContextCut PRO License ──"
  echo "  Your license key was sent to your email after purchase on Gumroad."
  echo "  It looks like: CC-PRO-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  echo ""
  read -p "PRO License key: " LICENSE_KEY
  if [ -z "$LICENSE_KEY" ]; then
    echo "ERROR: License key is required. Purchase at https://5984630877416.gumroad.com/l/ContextCut-Pro"
    exit 1
  fi
fi

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
    echo "  Docker not found. Install Qdrant manually:"
    echo "  Docker not found. Install Qdrant manually:"
    echo "    https://qdrant.tech/documentation/quick-start/"
    echo "  Or install Docker Desktop: https://docker.com"
    echo "  ....."    
    echo "  after startup of docker desktop open a terminal and run"
    echo "  docker run -d --name qdrant --restart always -p 6333:6333 -v $HOME/contextcut/qdrant_storage:/qdrant/storage  qdrant/qdrant "
    echo "  ..... expected output below....."    
    echo "    Unable to find image 'qdrant/qdrant:latest' locally"
    echo "    latest: Pulling from qdrant/qdrant"
    echo "    4f4fb700ef54: Pull complete ......"
    echo "    .... 6c998556d346: Download complete"
    echo "    Digest: sha256:94728574965d17c6485dd361aa3c0818b325b9016dac5ea6afec7b4b2700865f"
    echo "    Status: Downloaded newer image for qdrant/qdrant:latest a0e3245612b372b9c387205491c2242773379d6689e9e0b04fef6fe2da924971"
    echo "  ......... after install.... "
    echo "  docker ps "
    echo "        Expected output... "
    echo "        CONTAINER ID   IMAGE           COMMAND             CREATED          STATUS          PORTS                                         NAMES"
    echo "        a0e3245612b3   qdrant/qdrant   ./entrypoint.sh   27 minutes ago   Up 27 minutes   0.0.0.0:6333->6333/tcp, [::]:6333->6333/tcp   qdrant "
    echo " . test endpoints ..."
    echo "   curl http://localhost:6333/collections "
    echo "       Expected output... "
    echo "        {result:{collections:[]},status:ok,time:0.000010051} "
    echo "   ...................."
    echo "  mkdir  /home/steve/qdrant_storage "
    echo "  docker stop qdrant   # or whatever your container name is"
    echo "  docker rm -f qdrant " 
    echo "  ..."
    echo " docker run -d --name qdrant -p 6333:6333 -p 6334:6334 -v /home/steve/qdrant_storage:/qdrant/storage:z --restart unless-stopped  qdrant/qdrant:latest"
    echo " Expected outpue:  b0a483b80871e128110ff48d87a0ae33f76244467850149b50b409062c88371b "
    echo "  ..."
    echo "  NOW RE-RUN /tmp/start.sh  using  [localhost] and port [6333]  for qdrant "

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
curl -sf "$REPO/qdrant_proxy_final.py" -o "$INSTALL_DIR/qdrant_proxy_final.py"
curl -sf "$REPO/ingest.py"       -o "$INSTALL_DIR/ingest.py"

# ── Write env file ────────────────────────────────────────────────────────────
cat > "$INSTALL_DIR/.env" << EOF
CONTEXTCUT_LICENSE_KEY=$LICENSE_KEY
CONTEXTCUT_LICENSE_SERVER=https://contextcut-license.ppsel03.workers.dev
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
$INSTALL_DIR/venv/bin/python $INSTALL_DIR/qdrant_proxy_final.py &
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
