#!/bin/bash
# ContextCut uninstaller (Linux)
INSTALL_DIR="$HOME/contextcut"

echo ""
echo "  ContextCut Uninstaller"
echo "  ──────────────────────"
echo ""

# ── Stop proxy + watcher + release license seat ──
if [ -f "$INSTALL_DIR/stop.sh" ]; then
  echo "  Stopping services..."
  bash "$INSTALL_DIR/stop.sh"
  echo ""
else
  echo "  (no stop.sh found — skipping graceful shutdown)"
fi

# ── Stop & remove Qdrant Docker container ──
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx qdrant; then
  echo "  Stopping and removing Qdrant Docker container..."
  docker stop qdrant > /dev/null 2>&1
  docker rm qdrant > /dev/null 2>&1
  echo "  Qdrant container removed."
  echo ""
fi

# ── Remove systemd service if present ──
if [ -f /etc/systemd/system/contextcut-proxy.service ]; then
  echo "  Removing systemd service..."
  sudo systemctl stop contextcut-proxy 2>/dev/null
  sudo systemctl disable contextcut-proxy 2>/dev/null
  sudo rm /etc/systemd/system/contextcut-proxy.service
  sudo systemctl daemon-reload
  echo "  systemd service removed."
  echo ""
fi

# ── Confirm data deletion ──
echo "  WARNING: This will permanently delete:"
echo "    $INSTALL_DIR/              (proxy, config, KB files, Qdrant storage)"
echo "    $HOME/.contextcut/         (logs, instance secret)"
echo ""
read -p "  Delete all ContextCut data? [y/N]: " CONFIRM
if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
  rm -rf "$INSTALL_DIR"
  rm -rf "$HOME/.contextcut"
  # Also remove Qdrant Docker volume data if stored outside
  if docker volume ls -q 2>/dev/null | grep -qx qdrant_storage; then
    docker volume rm qdrant_storage > /dev/null 2>&1 && echo "  Qdrant Docker volume removed."
  fi
  echo "  All ContextCut data removed."
else
  echo "  Skipping data deletion."
fi

echo ""
echo "  Done."
