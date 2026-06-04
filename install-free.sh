#!/usr/bin/env bash
# ContextCut-Free installer — local RAG chat, one file, no Docker, no license.
set -euo pipefail
VERSION="1.0.0"

REPO_BASE="${REPO_BASE:-https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main}"
INSTALL_DIR="${CC_INSTALL_DIR:-$HOME/.contextcut-free}"
KB_DIR="${CC_KB_DIR:-$HOME/contextcut-free/knowledge}"
OLLAMA_HOST="${CC_OLLAMA_HOST:-localhost}"
OLLAMA_PORT="${CC_OLLAMA_PORT:-11434}"
CHAT_MODEL="${CC_CHAT_MODEL:-qwen2.5:7b}"
EMBED_MODEL="${CC_EMBED_MODEL:-nomic-embed-text}"
CTX_LIMIT="${CC_CTX_LIMIT:-32768}"
CC_PORT="${CC_PORT:-18788}"

PYTHON=$(command -v python3 || command -v python || true)

if [ -z "$PYTHON" ]; then
  for p in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    [ -x "$p" ] && { PYTHON="$p"; break; }
  done
fi

if [ -z "$PYTHON" ] && [ -f /etc/os-release ]; then
  . /etc/os-release
  if [[ "$ID" =~ ^(ubuntu|debian)$ ]]; then
    echo ""
    echo -e "${CYAN}==>${NC} Python 3 not found — installing via apt..."
    sudo apt update -qq && sudo apt install -y -qq python3 python3-pip python3-venv
    PYTHON=$(command -v python3 || true)
  fi
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}==>${NC} $1"; }
ok()   { echo -e "${GREEN}  OK${NC} $1"; }
err()  { echo -e "${RED}  FAIL${NC} $1"; }
warn() { echo -e "  WARN $1"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) OLLAMA_HOST="$2"; shift 2 ;;
    --port) OLLAMA_PORT="$2"; shift 2 ;;
    --chat-model) CHAT_MODEL="$2"; shift 2 ;;
    --embed-model) EMBED_MODEL="$2"; shift 2 ;;
    --ctx-limit) CTX_LIMIT="$2"; shift 2 ;;
    --cc-port) CC_PORT="$2"; shift 2 ;;
    --no-systemd) NO_SYSTEMD=true; shift ;;
    --uninstall) UNINSTALL=true; shift ;;
    --help|-h)
      echo "ContextCut-Free v${VERSION} installer"
      echo "Usage: bash install-free.sh [options]"
      echo ""
      echo "Install options:"
      echo "  --host <host>       Ollama host (default: $OLLAMA_HOST)"
      echo "  --port <port>       Ollama port (default: $OLLAMA_PORT)"
      echo "  --chat-model <m>    Chat model (default: $CHAT_MODEL)"
      echo "  --embed-model <m>   Embed model (default: $EMBED_MODEL)"
      echo "  --ctx-limit <n>     Context limit (default: $CTX_LIMIT)"
      echo "  --cc-port <n>       Dashboard port (default: $CC_PORT)"
      echo "  --no-systemd        Skip systemd service setup"
      echo ""
      echo "Other:"
      echo "  --uninstall         Remove ContextCut-Free and all data"
      echo "  --help              Show this help"
      exit 0 ;;
    *) err "Unknown: $1"; exit 1 ;;
  esac
done

if [ "${UNINSTALL:-false}" = true ]; then
  echo ""
  info "ContextCut-Free v${VERSION} — Uninstall"
  echo ""
  if command -v systemctl &>/dev/null; then
    info "Stopping and removing systemd service..."
    sudo systemctl stop contextcut-free 2>/dev/null || true
    sudo systemctl disable contextcut-free 2>/dev/null || true
    sudo rm -f /etc/systemd/system/contextcut-free.service
    sudo systemctl daemon-reload
    ok "Service removed"
  fi
  if [ -d "$INSTALL_DIR" ]; then
    info "Removing $INSTALL_DIR ..."
    rm -rf "$INSTALL_DIR"
    ok "Install directory removed"
  fi
  echo ""
  ok "ContextCut-Free uninstalled."
  info "KB dir preserved at: $KB_DIR (remove manually if desired)"
  exit 0
fi

if [ -z "$PYTHON" ]; then err "Python 3 not found (install python3)"; exit 1; fi
PYVER=$($PYTHON --version 2>&1 | grep -oE '\d+\.\d+' || echo "0")
if [ "${PYVER%%.*}" -lt 3 ]; then err "Python 3+ required, found $PYVER"; exit 1; fi
if ! command -v curl &>/dev/null; then err "curl not found"; exit 1; fi

echo ""
info "ContextCut-Free v${VERSION} Installer"
info "Target:   $INSTALL_DIR"
info "KB dir:   $KB_DIR"
info "Ollama:   ${OLLAMA_HOST}:${OLLAMA_PORT}"
info "Chat:     ${CHAT_MODEL}"
info "Embed:    ${EMBED_MODEL}"
info "Context:  ${CTX_LIMIT}"
info "Port:     ${CC_PORT}"
echo ""

mkdir -p "$INSTALL_DIR" "$KB_DIR"

info "Downloading cc-free.py..."
curl -sSf "$REPO_BASE/cc-free.py" -o "$INSTALL_DIR/cc-free.py"
chmod +x "$INSTALL_DIR/cc-free.py"
ok "cc-free.py saved"

cat > "$INSTALL_DIR/env" <<ENVEOF
OLLAMA_HOST=$OLLAMA_HOST
OLLAMA_PORT=$OLLAMA_PORT
CC_CHAT_MODEL=$CHAT_MODEL
CC_EMBED_MODEL=$EMBED_MODEL
CC_CTX_LIMIT=$CTX_LIMIT
CC_PORT=$CC_PORT
CC_DATA_DIR=$INSTALL_DIR
CC_KB_DIR=$KB_DIR
ENVEOF
ok "Config written to $INSTALL_DIR/env"

info "Installing Python dependencies..."
$PYTHON -m pip install --quiet --upgrade pip 2>/dev/null || true
FAISS_OK=false
if $PYTHON -c "import faiss" 2>/dev/null; then
  FAISS_OK=true
  ok "faiss already installed"
else
  if $PYTHON -m pip install --quiet faiss-cpu numpy 2>/dev/null; then
    FAISS_OK=true
    ok "faiss-cpu + numpy"
  elif [ "$(uname)" = "Darwin" ] && command -v brew &>/dev/null; then
    warn "faiss-cpu needs libomp — installing via Homebrew..."
    brew install libomp 2>/dev/null && \
    $PYTHON -m pip install --quiet faiss-cpu numpy 2>/dev/null && \
    FAISS_OK=true && ok "faiss-cpu + numpy (with libomp)"
  fi
fi
if [ "$FAISS_OK" = false ]; then
  $PYTHON -m pip install --quiet numpy 2>/dev/null || true
  warn "faiss-cpu install failed — falling back to numpy-only (slower)"
  warn "  To fix: brew install libomp && pip install faiss-cpu"
fi
$PYTHON -m pip install --quiet duckduckgo_search 2>/dev/null && ok "duckduckgo_search" || true

if command -v systemctl &>/dev/null && [ "${NO_SYSTEMD:-false}" = false ]; then
  info "Setting up systemd service..."
  START_CMD="$PYTHON $INSTALL_DIR/cc-free.py"
  sudo tee /etc/systemd/system/contextcut-free.service >/dev/null <<SERVICEEOF
[Unit]
Description=ContextCut-Free — local RAG chat
After=network-online.target

[Service]
Type=simple
User=$USER
ExecStart=$START_CMD
EnvironmentFile=$INSTALL_DIR/env
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SERVICEEOF
  sudo systemctl daemon-reload
  sudo systemctl enable contextcut-free
  sudo systemctl restart contextcut-free
  ok "Service contextcut-free started"
  LOG_CMD="journalctl -u contextcut-free -f"
else
  LOG_CMD="(run manually: $PYTHON $INSTALL_DIR/cc-free.py &)"
  warn "systemd not available — start in background:"
  warn "  $LOG_CMD"
fi

echo ""
ok "ContextCut-Free installed!"
info "Dashboard: http://localhost:${CC_PORT}"
info "Config:    $INSTALL_DIR/env"
info "KB dir:    $KB_DIR"
info "Logs:      ${LOG_CMD}"
echo ""
info "Upgrade to PRO: https://api.contextcut-pro.com"
