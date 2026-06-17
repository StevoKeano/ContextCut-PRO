#!/bin/bash
# ContextCut installer — macOS / Linux
# https://github.com/StevoKeano/ContextCut

REPO="${REPO_OVERRIDE:-https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main}"
INSTALL_DIR="$HOME/contextcut"
LOG_DIR="$HOME/.contextcut/logs"
PLIST_PROXY="$HOME/Library/LaunchAgents/ai.contextcut.proxy.plist"
PLIST_INGEST="$HOME/Library/LaunchAgents/ai.contextcut.ingest.plist"
PLIST_MCP="$HOME/Library/LaunchAgents/ai.contextcut.mcp.plist"
IS_MAC=false
[ "$(uname)" = "Darwin" ] && IS_MAC=true

echo ""
echo "  ContextCut installer"
echo "  Stop wasting tokens. Inject only what matters."
echo "  ──────────────────────────────────────────────"
echo ""

# ── Detect auto-install mode ─────────────────────────────────
AUTO_INSTALL=false
NONINTERACTIVE=false
if [ -n "$CONTEXTCUT_LICENSE_KEY" ]; then
  LICENSE_KEY="$CONTEXTCUT_LICENSE_KEY"
  # If VOYAGE_KEY is explicitly set (even empty), use full env-var config mode
  if [ "${VOYAGE_KEY+set}" = "set" ]; then
    NONINTERACTIVE=true
    echo ""
    echo "  ── ContextCut PRO License ──"
    echo "  License key detected: ${LICENSE_KEY:0:16}..."
    echo "  Configuration loaded from environment."
    if [ -z "$VOYAGE_KEY" ]; then
      EMBED_MODE="ollama"
      EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
    else
      EMBED_MODE="voyage"
    fi
    OLLAMA_HOST="${OLLAMA_HOST:-localhost}"
    OLLAMA_PORT="${OLLAMA_PORT:-11434}"
    QDRANT_HOST="${QDRANT_HOST:-localhost}"
    QDRANT_PORT="${QDRANT_PORT:-6333}"
    KB_DIR="${KB_DIR:-$INSTALL_DIR/knowledge}"
    PROXY_PORT="${PROXY_PORT:-18788}"
    DASH_PORT="${DASH_PORT:-18787}"
    MCP_PORT="${MCP_PORT:-8910}"
    CTX_LIMIT="${CTX_LIMIT:-32768}"
    MIN_SCORE="${MIN_SCORE:-0.50}"
  else
    AUTO_INSTALL=true
    echo ""
    echo "  ── ContextCut PRO License ──"
    echo "  License key detected automatically: ${LICENSE_KEY:0:16}..."
    exec < /dev/tty
  fi
fi

# ── Collect config (skip if env-var mode) ─────────────────────────────────────
if ! $NONINTERACTIVE; then
  if $AUTO_INSTALL; then
    echo ""
    echo "  ── Configuration ──"
    echo "  Defaults shown in [brackets]. Press Enter to accept, or type a new value."
    echo ""

    read -p "  Voyage AI API key (leave blank for local Ollama embedding): " VOYAGE_KEY

    if [ -z "$VOYAGE_KEY" ]; then
      echo "  100% local mode — using Ollama for embeddings."
      EMBED_MODE="ollama"
      read -p "  Embedding model [nomic-embed-text]: " EMBED_MODEL
      EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
    else
      EMBED_MODE="voyage"
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

    read -p "  MCP knowledge server port [8910]: " MCP_PORT
    MCP_PORT="${MCP_PORT:-8910}"

    read -p "  Model context limit [32768]: " CTX_LIMIT
    CTX_LIMIT="${CTX_LIMIT:-32768}"

    read -p "  Minimum relevance score 0.0-1.0 [0.50]: " MIN_SCORE
    MIN_SCORE="${MIN_SCORE:-0.50}"

    echo ""
    echo "  ── Confirm Your Settings ──"
    echo "  License key : ${LICENSE_KEY:0:16}..."
    echo "  Voyage API  : ${VOYAGE_KEY:0:8}..."
    echo "  Ollama      : $OLLAMA_HOST:$OLLAMA_PORT"
    echo "  Qdrant      : $QDRANT_HOST:$QDRANT_PORT"
    echo "  KB dir      : $KB_DIR"
    echo "  Proxy       : http://localhost:$PROXY_PORT"
    echo "  Dashboard   : http://localhost:$DASH_PORT"
    echo "  MCP server  : http://localhost:$MCP_PORT"
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

    read -p "  Voyage AI API key (leave blank for local Ollama embedding): " VOYAGE_KEY

    if [ -z "$VOYAGE_KEY" ]; then
      echo "  100% local mode — using Ollama for embeddings."
      EMBED_MODE="ollama"
      read -p "  Embedding model [nomic-embed-text]: " EMBED_MODEL
      EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
    else
      EMBED_MODE="voyage"
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

    read -p "  Model context limit [32768]: " CTX_LIMIT
    CTX_LIMIT="${CTX_LIMIT:-32768}"

    read -p "  Minimum relevance score 0.0-1.0 [0.50]: " MIN_SCORE
    MIN_SCORE="${MIN_SCORE:-0.50}"
  fi
fi

echo ""
echo "  ── Summary ──"
if [ -n "$VOYAGE_KEY" ]; then
  echo "  Embed mode  : Voyage AI (voyage-3)"
else
  echo "  Embed mode  : Ollama local ($EMBED_MODEL)"
fi
echo "  Install dir : $INSTALL_DIR"
echo "  Qdrant      : $QDRANT_HOST:$QDRANT_PORT"
echo "  Ollama      : $OLLAMA_HOST:$OLLAMA_PORT"
echo "  Dashboard   : port $DASH_PORT"
echo "  Proxy       : port $PROXY_PORT"
echo ""

if $AUTO_INSTALL && ! $NONINTERACTIVE; then
  read -p "  Proceed with install? [Y/n]: " ANSWER
  if echo "$ANSWER" | grep -qi "^n"; then
    echo ""
    echo "  Install aborted."
    echo ""
    echo "  To restart the install:"
    echo "    bash $0"
    echo ""
    exit 0
  fi
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
  if $NONINTERACTIVE; then
    if command -v docker &>/dev/null; then
      echo "  Auto-starting Qdrant via Docker..."
      docker run -d --name qdrant --restart always \
        -p "127.0.0.1:$QDRANT_PORT:6333" \
        -v "$INSTALL_DIR/qdrant_storage:/qdrant/storage" \
        qdrant/qdrant
      echo "  Qdrant started. Waiting 5s..."
      sleep 5
    else
      echo "  Auto-installing Qdrant natively..."
      ARCH="x86_64"
      if [ "$(uname -m)" = "aarch64" ]; then ARCH="aarch64"; fi
      QD_URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-${ARCH}-unknown-linux-gnu.tar.gz"
      TMP_DIR=$(mktemp -d)
      curl -sSL "$QD_URL" -o "$TMP_DIR/qdrant.tar.gz" || { echo "  Download failed"; exit 1; }
      tar -xzf "$TMP_DIR/qdrant.tar.gz" -C "$TMP_DIR" || { echo "  Extract failed"; exit 1; }
      sudo mv "$TMP_DIR/qdrant" /usr/local/bin/qdrant
      rm -rf "$TMP_DIR"
      echo "  Qdrant binary installed to /usr/local/bin/qdrant"
      mkdir -p "$INSTALL_DIR/qdrant_storage"
      sudo tee /etc/systemd/system/qdrant.service > /dev/null << 'QDSVC'
[Unit]
Description=Qdrant vector database
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/qdrant --uri http://127.0.0.1:6333
WorkingDirectory=/var/lib/qdrant
Restart=on-failure

[Install]
WantedBy=multi-user.target
QDSVC
      sudo mkdir -p /var/lib/qdrant
      sudo systemctl daemon-reload
      sudo systemctl enable --now qdrant
      echo "  Qdrant service started. Waiting 5s..."
      sleep 5
    fi
  else
  if command -v docker &>/dev/null; then
    read -p "  Start Qdrant via Docker now? [y/N]: " START_QDRANT
    if [ "$START_QDRANT" = "y" ] || [ "$START_QDRANT" = "Y" ]; then
      docker run -d --name qdrant --restart always \
        -p "127.0.0.1:$QDRANT_PORT:6333" \
        -v "$INSTALL_DIR/qdrant_storage:/qdrant/storage" \
        qdrant/qdrant
      echo "  Qdrant started. Waiting 5s..."
      sleep 5
    fi
  else
    echo "  Docker not found."
    echo "  ─────────────────────────────────────────────────────"
    echo "  1) Install Docker engine (Ubuntu/Debian):"
    echo '       sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io'
    echo "       sudo systemctl enable --now docker"
    echo ""
    echo "  2) Install Qdrant natively (no Docker):"
    echo "       Downloads the Qdrant binary + creates a systemd service."
    echo ""
    read -p "  Choose [1] Docker, [2] native Qdrant, or [N] abort: " QD_CHOICE
    if [ "$QD_CHOICE" = "1" ]; then
      echo '  Install Docker manually, then re-run this script.'
      echo "  https://docs.docker.com/engine/install/ubuntu/"
      exit 1
    elif [ "$QD_CHOICE" = "2" ]; then
      echo "  Installing Qdrant natively..."
      ARCH="x86_64"
      if [ "$(uname -m)" = "aarch64" ]; then ARCH="aarch64"; fi
      QD_URL="https://github.com/qdrant/qdrant/releases/latest/download/qdrant-${ARCH}-unknown-linux-gnu.tar.gz"
      TMP_DIR=$(mktemp -d)
      echo "  Downloading Qdrant from GitHub..."
      curl -sSL "$QD_URL" -o "$TMP_DIR/qdrant.tar.gz" || { echo "  Download failed"; exit 1; }
      tar -xzf "$TMP_DIR/qdrant.tar.gz" -C "$TMP_DIR" || { echo "  Extract failed"; exit 1; }
      if [ ! -f "$TMP_DIR/qdrant" ]; then
        echo "  ERROR: qdrant binary not found in tarball. Contents:"; ls -la "$TMP_DIR"
        exit 1
      fi
      sudo mv "$TMP_DIR/qdrant" /usr/local/bin/qdrant
      rm -rf "$TMP_DIR"
      echo "  Qdrant binary installed to /usr/local/bin/qdrant"
      mkdir -p "$INSTALL_DIR/qdrant_storage"
      sudo tee /etc/systemd/system/qdrant.service > /dev/null << 'QDSVC'
[Unit]
Description=Qdrant vector database
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/qdrant --uri http://127.0.0.1:6333
WorkingDirectory=/var/lib/qdrant
Restart=on-failure

[Install]
WantedBy=multi-user.target
QDSVC
      sudo mkdir -p /var/lib/qdrant
      sudo systemctl daemon-reload
      sudo systemctl enable --now qdrant
      echo "  Qdrant service started. Waiting 5s..."
      sleep 5
    else
      echo "  Aborted. Install Qdrant manually, then re-run."
      echo "  https://qdrant.tech/documentation/quick-start/"
      exit 1
    fi
  fi
fi
fi

# ── Python venv ───────────────────────────────────────────────────────────────
echo "  Creating Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv" || { echo "ERROR: venv creation failed"; exit 1; }
source "$INSTALL_DIR/venv/bin/activate"

echo "  Installing Python dependencies..."
pip install --upgrade pip -q 2>/dev/null
curl -sf "$REPO/requirements.txt" -o "$INSTALL_DIR/requirements.txt"
pip install -r "$INSTALL_DIR/requirements.txt" -q
if [ -n "$VOYAGE_KEY" ]; then
  pip install voyageai -q && echo "  voyageai installed" || echo "  WARNING: voyageai install failed (Voyage AI mode will not work)"
fi

# ── Download scripts ──────────────────────────────────────────────────────────
echo "  Downloading ContextCut scripts..."
curl -sf "$REPO/qdrant_proxy_final.py"  -o "$INSTALL_DIR/qdrant_proxy_final.py"
curl -sf "$REPO/ingest.py"              -o "$INSTALL_DIR/ingest.py"
curl -sf "$REPO/datasette.yml"          -o "$INSTALL_DIR/datasette.yml"
curl -sf "$REPO/run_datasette.sh"       -o "$INSTALL_DIR/run_datasette.sh"
curl -sf "$REPO/uninstall.sh"           -o "$INSTALL_DIR/uninstall.sh"
curl -sf "$REPO/agent_handler.py"       -o "$INSTALL_DIR/agent_handler.py"
curl -sf "$REPO/mcp_knowledge_server.py" -o "$INSTALL_DIR/mcp_knowledge_server.py"
chmod +x "$INSTALL_DIR/uninstall.sh"
chmod +x "$INSTALL_DIR/run_datasette.sh"

# ── Download starter knowledge files ─────────────────────────────────────────
STARTER_DIR="$INSTALL_DIR/starterKnowledgeFiles"
mkdir -p "$STARTER_DIR"
STARTER_FILES="advisor-ESTATE.md advisor-INVESTMENT.md advisor-RETIREMENT.md architect-CONTRACT.md architect-REGULATORY.md base-COMMUNICATION.md base-COMPLIANCE.md base-DEADLINES.md base-DRAFTING.md base-ETHICS.md base-RESEARCH.md base-REVIEW.md base-SKILL.md consultant-DELIVERABLE.md consultant-ENGAGEMENT.md consultant-METHODOLOGY.md cpa-corp-COMPLIANCE.md cpa-corp-INTL.md cpa-corp-MERGER.md cpa-corp-TAX.md cpa-corp-TRANSFER.md cpa-personal-DEDUCTION.md cpa-personal-ESTATE.md cpa-personal-INCOME.md cpa-personal-INVESTMENT.md cpa-personal-RETIREMENT.md cpa-smb-BOOKS.md cpa-smb-ENTITY.md cpa-smb-PAYROLL.md cpa-smb-QBI.md cpa-smb-SELFEMPLOYED.md customer_setup.md doctor-BILLING.md doctor-CLINICAL.md doctor-ETHICS.md doctor-PATIENT.md doctor-PRACTICE.md doctor-REGULATORY.md doctor-RESEARCH.md lawyer-lit-APPEAL.md lawyer-lit-DISCOVERY.md lawyer-lit-EVIDENCE.md lawyer-lit-MOTIONS.md lawyer-lit-PLEADING.md lawyer-re-CLOSING.md lawyer-re-LEASE.md lawyer-re-PURCHASE.md lawyer-re-TITLE.md lawyer-re-ZONING.md lawyer-smb-CONTRACT.md lawyer-smb-EMPLOYMENT.md lawyer-smb-ENTITY.md lawyer-smb-IP.md lawyer-smb-REGULATORY.md realtor-CONTRACT.md realtor-DISCLOSURE.md realtor-LISTING.md tech-CONTRACT.md tech-PRIVACY.md"
for f in $STARTER_FILES; do
  curl -sf "$REPO/starterKnowledgeFiles/$f" -o "$STARTER_DIR/$f"
done
echo "  Starter knowledge files: $(echo $STARTER_FILES | wc -w) files in starterKnowledgeFiles/"
# Copy selected categories to knowledge base
if [ -n "$STARTER_CATEGORIES" ]; then
  KB_DIR="${KB_DIR:-$INSTALL_DIR/knowledge}"
  echo "  Copying selected starter files to $KB_DIR ..."
  OLD_IFS="$IFS"; IFS=','
  for cat in $STARTER_CATEGORIES; do
    count=0
    if [ "$cat" = "customer_setup" ]; then
      cp "$STARTER_DIR/customer_setup.md" "$KB_DIR/" 2>/dev/null && count=1
    else
      for f in "$STARTER_DIR/$cat-"*; do
        if [ -f "$f" ]; then
          cp "$f" "$KB_DIR/" 2>/dev/null && count=$((count+1))
        fi
      done
    fi
    [ $count -gt 0 ] && echo "    $cat: $count files copied"
  done
  IFS="$OLD_IFS"
fi
echo ""

# ── Privacy: disable Ollama telemetry ────────────────────────────────────────
if [ "$(uname)" != "Darwin" ]; then
  echo "  \033[33mPrivacy:\033[0m Set OLLAMA_NO_CLOUD=true in your Ollama environment to disable"
  echo "          all outbound calls to ollama.com. On the Ollama host, add:"
  echo "            export OLLAMA_NO_CLOUD=true"
  echo "          (Windows: run as Admin: setx OLLAMA_NO_CLOUD true /M)"
fi

# ── Write env file ────────────────────────────────────────────────────────────
INSTANCE_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
cat > "$INSTALL_DIR/.env" << EOF
CONTEXTCUT_LICENSE_KEY=$LICENSE_KEY
CONTEXTCUT_INSTANCE_ID=$INSTANCE_ID
CONTEXTCUT_LICENSE_SERVER=https://api.contextcut-pro.com
VOYAGE_API_KEY=$VOYAGE_KEY
CONTEXTCUT_EMBED_MODE=$EMBED_MODE
CONTEXTCUT_EMBED_MODEL=$EMBED_MODEL
CONTEXTCUT_UPSTREAM=http://$OLLAMA_HOST:$OLLAMA_PORT
CONTEXTCUT_QDRANT_HOST=$QDRANT_HOST
CONTEXTCUT_QDRANT_PORT=$QDRANT_PORT
CONTEXTCUT_KB_DIR=$KB_DIR
CONTEXTCUT_PROXY_PORT=$PROXY_PORT
CONTEXTCUT_DASHBOARD_PORT=$DASH_PORT
CONTEXTCUT_MCP_PORT=$MCP_PORT
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
RESULT=$(curl -sf -X POST "https://api.contextcut-pro.com/v1/license/reset" \
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
    <key>CONTEXTCUT_LICENSE_SERVER</key><string>https://api.contextcut-pro.com</string>
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

  cat > "$PLIST_MCP" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>ai.contextcut.mcp</string>
  <key>Comment</key><string>ContextCut MCP Knowledge Server</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/venv/bin/python</string>
    <string>$INSTALL_DIR/mcp_knowledge_server.py</string>
    <string>--transport</string>
    <string>http</string>
    <string>--port</string>
    <string>$MCP_PORT</string>
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/mcp.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/mcp.err.log</string>
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

  plutil -lint "$PLIST_PROXY"  > /dev/null && echo "  Proxy plist OK"
  plutil -lint "$PLIST_INGEST" > /dev/null && echo "  Ingest plist OK"

  launchctl bootstrap gui/$(id -u) "$PLIST_PROXY"
  launchctl bootstrap gui/$(id -u) "$PLIST_INGEST"
  echo "  launchd agents started."

else
  # Linux — write start/stop scripts
  cat > "$INSTALL_DIR/start.sh" << 'STARTEOF'
#!/bin/bash
INST="$(dirname "$0")"

# Clean stale ready file
rm -f "$INST/.proxy_ready"

# ── Start proxy first (it ensures correct collection dimension) ──
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

# ── Start watcher ──
WATCHER_PIDFILE="$INST/.ingest.pid"
if [ -f "$WATCHER_PIDFILE" ] && kill -0 $(cat "$WATCHER_PIDFILE") 2>/dev/null; then
  echo "Watcher already running (PID $(cat "$WATCHER_PIDFILE"))."
else
  "$INST/venv/bin/python" "$INST/ingest.py" --watch &
  echo $! > "$WATCHER_PIDFILE"
  echo "Watcher started. PID: $(cat "$WATCHER_PIDFILE")"
fi
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
STOPEOF
  chmod +x "$INSTALL_DIR/stop.sh"

  # ── systemd service (reboot-proof on Linux) ──
  mkdir -p "$HOME/.config/systemd/user"
  cat > "$HOME/.config/systemd/user/contextcut.service" << 'SERVICEEOF'
[Unit]
Description=ContextCut PRO — proxy + knowledge base watcher
After=network-online.target docker.service
Wants=network-online.target docker.service

[Service]
Type=simple
ExecStart=%h/contextcut/start.sh
ExecStop=%h/contextcut/stop.sh
Restart=on-failure
RestartSec=10
EnvironmentFile=%h/contextcut/.env

[Install]
WantedBy=default.target
SERVICEEOF
  echo "  systemd user service written to ~/.config/systemd/user/contextcut.service"
  echo "  To enable auto-start on boot:"
  echo "    systemctl --user daemon-reload"
  echo "    systemctl --user enable --now contextcut"
  echo "    sudo loginctl enable-linger $USER"
  echo ""

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
RESULT=$(curl -sf -X POST "https://api.contextcut-pro.com/v1/license/reset" \
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
if [ -n "$VOYAGE_KEY" ]; then
  echo "  Running initial knowledge base ingest..."
  echo "  (this may take a while — Voyage AI free tier: 1 file per 21s)"
else
  echo "  Running initial knowledge base ingest (local Ollama)..."
fi
echo ""
export VOYAGE_API_KEY="$VOYAGE_KEY"
export CONTEXTCUT_EMBED_MODE="$EMBED_MODE"
export CONTEXTCUT_EMBED_MODEL="$EMBED_MODEL"
export CONTEXTCUT_UPSTREAM="http://$OLLAMA_HOST:$OLLAMA_PORT"
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
echo "  MCP server: http://localhost:$MCP_PORT"
echo "  KB dir:     $KB_DIR"
echo "  Logs:       $LOG_DIR"
echo ""
echo "  Opening dashboard in your browser..."
if command -v xdg-open &>/dev/null; then
  xdg-open "http://localhost:$DASH_PORT" 2>/dev/null || true
elif command -v open &>/dev/null; then
  open "http://localhost:$DASH_PORT" 2>/dev/null || true
fi
echo "  ── Admin: Environment Variables ──"
echo "  If using Ollama on Windows, run an Admin cmd (one time) to disable telemetry:"
echo "    setx OLLAMA_NO_CLOUD true /M"
echo "  Then close all Ollama windows and restart Ollama — it reads env vars only at"
echo '  startup. On Linux, add `export OLLAMA_NO_CLOUD=true` to your Ollama service.'
echo "  Performance: OLLAMA_CONTEXT_LENGTH=32768 reduces KV cache from 5GB to ~1.25GB"
echo "  on a 14B q8_0 model, preventing GPU VRAM eviction."
echo ""
echo "  ── Reboot-proof (auto-start on boot) ──"
echo "  Linux:"
echo "    systemctl --user daemon-reload"
echo "    systemctl --user enable --now contextcut"
echo "    sudo loginctl enable-linger $USER"
echo "  macOS: launchd agents are already installed (auto-start on login)."
echo "  Windows: Create a scheduled task or shortcut in shell:startup:"
echo '    (New-Object -Com WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\ContextCut.lnk").TargetPath = "wsl.exe"; .Arguments = "-d Ubuntu -- ~/contextcut/start.sh"; .Save()'
echo ""
echo "  ── Quick Start ──"
echo "  1. Starter knowledge files are in: $STARTER_DIR"
echo "  2. Copy the ones relevant to you:"
echo "     cp $STARTER_DIR/lawyer-* $KB_DIR/     # lawyers"
echo "     cp $STARTER_DIR/cpa-* $KB_DIR/        # CPAs"
echo "     cp $STARTER_DIR/doctor-* $KB_DIR/     # doctors"
echo "     cp $STARTER_DIR/realtor-* $KB_DIR/    # realtors"
echo "     cp $STARTER_DIR/advisor-* $KB_DIR/    # financial advisors"
echo "     cp $STARTER_DIR/architect-* $KB_DIR/  # architects"
echo "     cp $STARTER_DIR/tech-* $KB_DIR/       # tech workers"
echo "     cp $STARTER_DIR/consultant-* $KB_DIR/ # consultants"
echo "     cp $STARTER_DIR/base-* $KB_DIR/       # universal templates"
echo "  3. Or add your own .md files to: $KB_DIR"
echo "  4. Files are auto-ingested within seconds."
echo "  5. Test the API:"
echo "     curl -X POST http://localhost:$PROXY_PORT/v1/chat/completions \\"
echo '       -H "Content-Type: application/json" \'
echo '       -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"model\":\"your-model-name\"}"'
echo ""
echo "  Add .md files to $KB_DIR and they will be auto-ingested."
echo ""
