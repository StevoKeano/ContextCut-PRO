# ContextCut PRO — Sales Pipeline Architecture

## Overview

```
Gumroad ──webhook──▶ Cloudflare Worker ──▶ Email (Resend)
                          │
                          ├── KV Store (licenses)
                          │
                          ├── /install/<KEY> ──▶ Shell script ──▶ install.sh
                          │
                          └── /v1/license/validate ◀── Proxy (heartbeat loop)
```

---

## 1. Gumroad Webhook → Cloudflare Worker

### Gumroad Configuration

1. Go to your Gumroad product → Settings → Advanced → **Ping**
2. Set URL: `https://api.contextcut-pro.com/webhook/gumroad`
3. Enable: "Send purchase pings on sale"
4. Gumroad sends a `POST` with `Content-Type: application/x-www-form-urlencoded`

### Gumroad Form Fields Received

| Field | Value | Used by worker |
|---|---|---|
| `resource_name` | `"sale"` | Required — worker skips if not `"sale"` |
| `product_name` | `"ContextCut PRO"` | Must include `"ContextCut"` |
| `email` | `user@example.com` | Sent to Resend for delivery |
| `order_number` | `"12345"` | Stored in KV to detect duplicates |
| `full_name` | `"John Doe"` | Not used |

### Worker: `/webhook/gumroad` Handler

```
POST /webhook/gumroad
```

**Validation flow:**

```
resource_name === "sale"?
  └── No → return {ok: true, skipped: true}
product_name.includes("ContextCut")?
  └── No → return {ok: true, skipped: true}
order:12345 already in KV?
  └── Yes → return {ok: true, duplicate: true}
```

**On first purchase:**

1. Generate UUID v4 → `CC-PRO-<uuid>`
2. Store `license:CC-PRO-<uuid>` → `"{}"` (empty JSON object for seat tracking)
3. Store `order:12345` → `CC-PRO-<uuid>` (prevents duplicate processing)
4. Send email via Resend (if configured)
5. Return `{ok: true, license_key, install_url}`

### KV Namespace: `LICENSE_KV`

| Key Pattern | Value | Purpose |
|---|---|---|
| `license:CC-PRO-<uuid>` | `{}` empty, then JSON with seat data | License seat tracking |
| `order:<gumroad_order_number>` | `CC-PRO-<uuid>` | Duplicate prevention |

---

## 2. Email Delivery via Resend

### Configuration

| Environment Variable | Value |
|---|---|
| `RESEND_API_KEY` | Your Resend API key (set in Cloudflare Worker secrets) |
| Sender domain | `contextcut.thehangarsatspicewood.com` (must be verified in Resend) |
| From address | `ContextCut PRO <noreply@contextcut.thehangarsatspicewood.com>` |

### Email Template

The worker sends a branded HTML email with:

- Welcome header
- License key (`CC-PRO-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)
- Seat count (3)
- **Quick Install** command: `curl -fsSL "<install_url>" | bash`
- **Manual Install** fallback command
- Link to GitHub setup guide

### Debugging Email Failures

```bash
# Check worker logs for Resend response
wrangler tail

# Look for:
# Webhook fields: JSON.stringify({ email, orderId, eventType, product })
# Resend response: <status> <body>
```

Common failures:
- Domain not verified in Resend → 403 from Resend API
- `RESEND_API_KEY` not set → email skipped silently
- Invalid email address → 422 from Resend API

---

## 3. Install Link → Shell Script

### Endpoint

```
GET /install/CC-PRO-<uuid>
```

### Response

Returns `Content-Type: text/x-sh` — a self-contained bash script:

```bash
#!/bin/bash
set -e
export CONTEXTCUT_LICENSE_KEY="CC-PRO-<uuid>"
SCRIPT_URL="https://raw.githubusercontent.com/StevoKeano/ContextCut-PRO/main/install.sh"
curl -fsSL "$SCRIPT_URL" -o /tmp/contextcut-install.sh
bash /tmp/contextcut-install.sh
```

### Security

- License key is validated against KV before returning the script
- Script is generated server-side, never cached client-side
- The `install.sh` is pulled directly from GitHub, not from the worker

---

## 4. Installer → License Validation

### `install.sh` Auto-Install Path

```
Customer runs: curl -fsSL "<install_url>" | bash

1. Script sets CONTEXTCUT_LICENSE_KEY=CC-PRO-<uuid>
2. Script downloads install.sh from GitHub main branch
3. install.sh detects CONTEXTCUT_LICENSE_KEY → AUTO_INSTALL=true
4. Calls: exec < /dev/tty (reconnects stdin to terminal)
5. Prompts: Voyage AI key, Ollama host/port, Qdrant host/port
6. Shows summary → prompts "Proceed with these settings? [Y/n]"
7. On 'y': installs proxy, watcher, writes .env
8. On 'n': exits
```

### Proxy License Validation (at startup)

```
Proxy starts → load_saved_credentials()
  → validate_license()
  → POST {license_key, instance_id, fingerprint} to worker
  → Worker checks KV for license key
  → Worker counts active seats (heartbeat within 30 min)
  → If seat available: activates, stores {instance_id, fingerprint, timestamp}
  → Returns {valid: true, license_type: "single", message: "License activated"}
```

### Heartbeat Loop

```
Every ~5 minutes (HEARTBEAT_INTERVAL = 300s):
  POST {license_key, instance_id} to worker
  Worker updates last_heartbeat timestamp
  If no heartbeat for 30 minutes (HEARTBEAT_TIMEOUT):
    Seat considered stale, available for reassignment
```

### Seat Release

```
On proxy shutdown:
  → POST {license_key, instance_id} to /v1/license/release
  → Removes instance from KV
  → Seat freed immediately

On license limit reached (auto-recovery):
  → POST {license_key} to /v1/license/reset
  → Wipes all seats → re-activates current instance
```

---

## 5. Worker API Reference

### `POST /webhook/gumroad`

Process Gumroad purchase ping.

| Parameter | Type | Description |
|---|---|---|
| `resource_name` | string | Must be `"sale"` |
| `product_name` | string | Must contain `"ContextCut"` |
| `email` | string | Customer email |
| `order_number` | string | Gumroad order ID |

### `GET /install/<license_key>`

Returns install script.

| Parameter | Location | Description |
|---|---|---|
| `license_key` | URL path | Must match `CC-PRO-<uuid>` pattern |

### `POST /v1/license/validate`

Activate or validate a license seat.

| Parameter | Type | Description |
|---|---|---|
| `license_key` | string | CC-PRO license key |
| `instance_id` | string | Unique machine ID |
| `fingerprint` | object | `{hostname, ...}` |

### `POST /v1/heartbeat`

Keep seat alive.

| Parameter | Type | Description |
|---|---|---|
| `license_key` | string | CC-PRO license key |
| `instance_id` | string | Unique machine ID |

### `POST /v1/license/release`

Free a seat.

| Parameter | Type | Description |
|---|---|---|
| `license_key` | string | CC-PRO license key |
| `instance_id` | string | Unique machine ID |

### `POST /v1/license/reset`

Wipe all seats (for auto-recovery on license limit errors).

| Parameter | Type | Description |
|---|---|---|
| `license_key` | string | CC-PRO license key |
| Header `X-Admin-Secret` | string | Must match `ADMIN_SECRET` env var |

### `GET /health`

Health check endpoint.

Returns `{status: "healthy", kv: "ok", uptime: "ok"}`

---

## 6. Monitoring & Debugging

### Worker Logs (tail)

```bash
wrangler tail
```

Shows all requests with path, method, status, and timestamps.

### KV Inspection

```bash
# List all keys (via wrangler or dashboard)
wrangler kv:key list --binding LICENSE_KV

# Get a specific license
wrangler kv:key get --binding LICENSE_KV "license:CC-PRO-<uuid>"

# Get order mapping
wrangler kv:key get --binding LICENSE_KV "order:<order_number>"
```

### License Health Check

Script at `license_health.sh` validates the full pipeline:

```bash
./license_health.sh

── 1. Worker Reachability ──
[PASS] Worker responds (404 for root is expected)

── 2. Webhook Endpoint ──
[PASS] Webhook created license: CC-PRO-<uuid>

── 3. Install Link ──
[PASS] Install URL returns shell script

── 4. License Validate ──
[PASS] License validation: valid=true

── 5. Heartbeat ──
[PASS] Heartbeat acknowledged

── 6. Seat Release ──
[PASS] Seat released successfully
```

---

## 7. Deployment

### Cloudflare Worker

```bash
# Login
wrangler login

# Deploy
wrangler deploy --name contextcut-license --compatibility-date 2024-01-01 cloudflare_worker.js

# Set environment variables
wrangler secret put RESEND_API_KEY
wrangler secret put ADMIN_SECRET

# Bind KV namespace
# wrangler.toml:
# [[kv_namespaces]]
# binding = "LICENSE_KV"
# id = "<namespace-id>"
```

### GitHub Pages Landing Page

```
https://stevokeano.github.io/ContextCut-PRO/

GitHub Pages auto-deploys from main branch.
Push to main → wait ~2 min → pages updated.
```

### Updating `install.sh`

```bash
# Push to main branch
git add install.sh
git commit -m "update installer"
git push

# Worker's /install/<KEY> script pulls from main branch
```

---

## 8. Field Name Reference

### Gumroad Webhook Fields vs. Worker Expectations

**Critical:** The test script must use Gumroad field names, not generic names:

| Gumroad Field Name | Worker Key | Test Value |
|---|---|---|
| `resource_name` | `body.get("resource_name")` | `"sale"` |
| `product_name` | `body.get("product_name")` | Must include "ContextCut" |
| `email` | `body.get("email")` | Valid email |
| `order_number` | `body.get("order_number")` | Gumroad order ID |

**Wrong test fields (will always skip):**

```bash
# ✗ WRONG — these field names don't match Gumroad format:
-d "event_type=sale_completed"
-d "order_id=hc-..."
```

**Correct test fields:**

```bash
# ✓ CORRECT — matches Gumroad field names:
-d "resource_name=sale"
-d "order_number=hc-..."
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Worker returns 403 on deploy | Dashboard session token expired | Use `wrangler deploy` CLI |
| Email not sent | `RESEND_API_KEY` missing or invalid | Check worker env vars |
| Email not delivered | Domain not verified in Resend | Add/verify domain in Resend dashboard |
| License validation returns 401 | License key not in KV | Check KV namespace contents |
| License validation returns 403 | All 3 seats used | Reset seats via `/v1/license/reset` |
| Install link returns 401 | Invalid or expired key | Verify key exists in KV |
| `curl | bash` prompts hang | `exec < /dev/tty` failed | Run install.sh directly: `bash install.sh` |
| Qdrant dimension mismatch | Switching between Ollama/Voyage | Re-ingest from dashboard settings |
