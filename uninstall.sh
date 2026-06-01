#!/bin/bash
# ContextCut uninstaller (Linux) — nukes everything
INSTALL_DIR="$HOME/contextcut"

echo ""
echo "  ContextCut Uninstaller"
echo "  ──────────────────────"
echo ""

# ── Kill any lingering processes ──
echo "  Killing proxy + watcher processes..."
kill $(pgrep -f "qdrant_proxy_final.py") 2>/dev/null
kill $(pgrep -f "ingest.py --watch") 2>/dev/null
kill $(pgrep -f "ingest.py") 2>/dev/null
sleep 1

# ── Stop gracefully if stop.sh exists ──
if [ -f "$INSTALL_DIR/stop.sh" ]; then
  echo "  Running stop.sh..."
  bash "$INSTALL_DIR/stop.sh" 2>/dev/null
fi

# ── Release license seat via stop.sh's logic if possible ──
ENV_FILE="$INSTALL_DIR/.env"
SECRET_FILE="$HOME/.contextcut/instance_secret"
if [ -f "$ENV_FILE" ] && [ -f "$SECRET_FILE" ]; then
  KEY=$(grep "^CONTEXTCUT_LICENSE_KEY=" "$ENV_FILE" | sed 's/^[^=]*=//; s/^["'\'']//; s/["'\'']$//')
  INSTANCE_ID=$(grep "^CONTEXTCUT_INSTANCE_ID=" "$ENV_FILE" | sed 's/^[^=]*=//; s/^["'\'']//; s/["'\'']$//')
  SECRET=$(cat "$SECRET_FILE")
  if [ -n "$KEY" ] && [ -n "$INSTANCE_ID" ] && [ -n "$SECRET" ]; then
    echo "  Releasing license seat..."
    curl -sf -X POST 'https://api.contextcut-pro.com/v1/license/release' \
      -H 'Content-Type: application/json' \
      -d '{"license_key":"'"$KEY"'","instance_id":"'"$INSTANCE_ID"'","instance_secret":"'"$SECRET"'"}' \
      > /dev/null 2>&1 && echo "  Seat released." || echo "  Release failed (seat expires in 30 min)."
  fi
fi

# ── User-level systemd service ──
if [ -f "$HOME/.config/systemd/user/contextcut.service" ]; then
  echo "  Removing user-level systemd service..."
  systemctl --user stop contextcut 2>/dev/null
  systemctl --user disable contextcut 2>/dev/null
  rm -f "$HOME/.config/systemd/user/contextcut.service"
  systemctl --user daemon-reload
  echo "  User-level systemd service removed."
fi

# ── Old system-level service (legacy) ──
if [ -f /etc/systemd/system/contextcut-proxy.service ]; then
  echo "  Removing legacy systemd service..."
  sudo systemctl stop contextcut-proxy 2>/dev/null
  sudo systemctl disable contextcut-proxy 2>/dev/null
  sudo rm /etc/systemd/system/contextcut-proxy.service
  sudo systemctl daemon-reload
  echo "  Legacy systemd service removed."
fi

# ── Qdrant Docker ──
if command -v docker &>/dev/null; then
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx qdrant; then
    echo "  Stopping and removing Qdrant Docker container..."
    docker stop qdrant > /dev/null 2>&1
    docker rm qdrant > /dev/null 2>&1
  fi
  if docker volume ls -q 2>/dev/null | grep -qx qdrant_storage; then
    echo "  Removing Qdrant Docker volume..."
    docker volume rm qdrant_storage > /dev/null 2>&1
  fi
  # Also try removing the qdrant/qdrant image (optional)
  if docker images -q qdrant/qdrant 2>/dev/null | head -1; then
    echo "  Removing qdrant/qdrant Docker image..."
    docker rmi qdrant/qdrant 2>/dev/null || true
  fi
fi

# ── Qdrant native binary ──
if [ -f /etc/systemd/system/qdrant.service ]; then
  echo "  Removing native Qdrant systemd service..."
  sudo systemctl stop qdrant 2>/dev/null
  sudo systemctl disable qdrant 2>/dev/null
  sudo rm /etc/systemd/system/qdrant.service
  sudo systemctl daemon-reload
fi
if [ -f /usr/local/bin/qdrant ]; then
  echo "  Removing Qdrant binary..."
  sudo rm -f /usr/local/bin/qdrant
fi

# ── Kill all remaining processes (safety net) ──
echo "  Cleaning up any remaining ContextCut processes..."
pkill -f "contextcut" 2>/dev/null
pkill -f "qdrant" 2>/dev/null

# ── Nuke everything under contextcut paths ──
echo "  Removing all ContextCut files and data..."
rm -rf "$INSTALL_DIR"
rm -rf "$HOME/.contextcut"
rm -rf "$HOME/.contextcut_sessions.db"

echo ""
echo "  Done. All ContextCut components removed."
echo ""
