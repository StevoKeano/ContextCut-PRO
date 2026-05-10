# ContextCut PRO — Setup Guide

Welcome to ContextCut PRO. Follow the steps below to get started.

## Quick Start

### 1. Get Your License Key

After purchasing on Gumroad, you'll receive an email with your license key and a **one-click install link**.

**One-command install (recommended):**
```bash
curl -fsSL "https://api.contextcut-pro.com/install/CC-PRO-YOUR-UUID" | bash
```
This downloads the installer with your license key pre-set. You'll be prompted for your Voyage AI API key during setup.

**Manual install:**
```bash
curl -fsSL https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main/install.sh | bash
```
You'll be prompted for your license key and Voyage API key during setup.

### 2. Requirements

- Python 3.10+
- [Voyage AI API key](https://dash.voyageai.com)
- [Qdrant](https://qdrant.tech) running locally
- Ollama or any OpenAI-compatible LLM endpoint
- Your PRO license key (provided at purchase)

### 2. Install Dependencies

```bash
pip install voyageai qdrant-client
```

### 3. Set Environment Variables

```bash
# Required
export VOYAGE_API_KEY="your-voyage-api-key"
export CONTEXTCUT_LICENSE_KEY="YOUR-PRO-LICENSE-KEY"
export CONTEXTCUT_LICENSE_SERVER="https://api.contextcut-pro.com"

# Optional (defaults shown)
export CONTEXTCUT_UPSTREAM="http://localhost:11434"
export CONTEXTCUT_QDRANT_HOST="localhost"
export CONTEXTCUT_QDRANT_PORT="6333"
export CONTEXTCUT_COLLECTION="contextcut"
export CONTEXTCUT_PROXY_PORT="18788"
export CONTEXTCUT_DASHBOARD_PORT="18787"
export CONTEXTCUT_CTX_LIMIT="8192"
export CONTEXTCUT_TOP_K="5"
export CONTEXTCUT_MIN_SCORE="0.30"
export CONTEXTCUT_MODEL=""
export CONTEXTCUT_TEMP="0.7"
export CONTEXTCUT_TOP_P="1.0"
export CONTEXTCUT_MAX_TOKENS="0"
```

### 4. Run

```bash
python3 qdrant_proxy_final.py
```

Expected output:
```
[contextcut] Validating license key...
[contextcut] License: single | License activated
[contextcut] Heartbeat: every 900s | grace: 3600s
[contextcut] Dashboard  → http://localhost:18787
[contextcut] Proxy      → http://127.0.0.1:18788 → http://localhost:11434
```

### 5. Stop

```
Ctrl-C
```

The license seat is released automatically on shutdown.

## License Management

Your license supports **concurrent instances** (check your purchase for seat count). Each running instance occupies one seat.

### Common Issues

| Problem | Solution |
|---|---|
| `License limit reached` | You exceeded your concurrent seat limit. Stop an existing instance, or wait 30 min for a stale seat to expire |
| `Invalid license key` | Double-check your key. If it still fails, contact support |
| `HTTP 403 / 1010` | Network or firewall issue. Ensure you can reach `https://api.contextcut-pro.com` |

### Reset Your Seats

If you have orphaned seats from a crash, reset them:

```bash
python3 license_tool.py reset --key YOUR-LICENSE-KEY
```

## Dashboard

Open `http://localhost:18787` for the PRO split-panel dashboard:
- **Left panel** — live stats, context usage bar, per-request token table
- **Right panel** — integrated chat with model selector and parameter controls

## Commands

| Command | Description |
|---|---|
| `/clear` | Clear conversation history |
| `/help` | Show available commands |

Natural commands the model responds to:
- `"stop"` / `"that's enough"` — stop current response
- `"continue"` / `"go on"` — continue previous response
- `"revise..."` / `"rewrite..."` — revise previous response

## Keyboard Shortcuts

| Key | Action |
|---|---|
| Enter | Send message |
| Shift+Enter | New line |
| ↑ (empty input) | Previous message |
| ↓ | Next message |

## Support

For issues or questions, contact: [your support email or link]
