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
