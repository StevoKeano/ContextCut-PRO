# Kill running services
pkill -f qdrant_proxy.py
pkill -f ingest.py

# Remove old install
rm -rf ~/contextcut
rm -f ~/Library/LaunchAgents/ai.contextcut.*.plist 2>/dev/null

# Fresh terminal recommended — or just clear env vars
unset VOYAGE_API_KEY CONTEXTCUT_UPSTREAM CONTEXTCUT_QDRANT_HOST CONTEXTCUT_QDRANT_PORT CONTEXTCUT_KB_DIR CONTEXTCUT_PROXY_PORT CONTEXTCUT_DASHBOARD_PORT CONTEXTCUT_CTX_LIMIT CONTEXTCUT_MIN_SCORE CONTEXTCUT_COLLECTION

# Verify ports are clear
lsof -i :18787
lsof -i :18788

# reinstall
curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut/main/install.sh -o /tmp/install.sh
chmod +x /tmp/install.sh
bash /tmp/install.sh