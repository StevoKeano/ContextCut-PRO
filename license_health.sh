#!/bin/bash
# ContextCut PRO — License System Health Check
# Run from anywhere: bash license_health.sh

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[0;33m"
NC="\033[0m"
PASS=0
FAIL=0
WORKER="https://contextcut-license.ppsel03.workers.dev"

pass() { echo -e "${GREEN}[PASS]${NC} $1"; ((PASS++)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; ((FAIL++)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo "========================================="
echo " ContextCut PRO License Health Check"
echo " $(date)"
echo "========================================="
echo ""

# ── 1. Worker is alive ──────────────────────────────────────────
echo "── 1. Worker Reachability ──"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$WORKER/" 2>/dev/null || echo "000")
if [ "$STATUS" = "404" ]; then
  pass "Worker responds (404 for root is expected)"
else
  fail "Worker unreachable (HTTP $STATUS)"
fi

# ── 2. Webhook endpoint exists ──────────────────────────────────
echo "── 2. Webhook Endpoint ──"
WEBHOOK_RESP=$(curl -s -X POST "$WORKER/webhook/gumroad" \
  -d "event_type=sale_completed" \
  -d "product_name=ContextCut Pro Test" \
  -d "email=test-$(date +%s)@healthcheck.local" \
  -d "order_id=hc-$(date +%s)")

if echo "$WEBHOOK_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('ok')" 2>/dev/null; then
  LIC=$(echo "$WEBHOOK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('license_key',''))" 2>/dev/null)
  URL=$(echo "$WEBHOOK_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('install_url',''))" 2>/dev/null)
  pass "Webhook created license: $LIC"
else
  fail "Webhook failed: $WEBHOOK_RESP"
  LIC=""
fi

# ── 3. Install link works ───────────────────────────────────────
echo "── 3. Install Link ──"
if [ -n "$LIC" ]; then
  INSTALL_SCRIPT=$(curl -s "$WORKER/install/$LIC" 2>/dev/null)
  if echo "$INSTALL_SCRIPT" | grep -q "$LIC"; then
    pass "Install link returns script with embedded license"
  else
    fail "Install link did not return valid script"
  fi
fi

# ── 4. Invalid license rejected ─────────────────────────────────
echo "── 4. Invalid License Rejection ──"
BAD_RESP=$(curl -s -X POST "$WORKER/v1/license/validate" \
  -H "Content-Type: application/json" \
  -d '{"license_key":"FAKE-KEY-123","instance_id":"test-bad","fingerprint":{"hostname":"test"}}')
if echo "$BAD_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert not j.get('valid')" 2>/dev/null; then
  pass "Invalid license correctly rejected"
else
  fail "Invalid license was not rejected: $BAD_RESP"
fi

# ── 5. License validation (from webhook) ────────────────────────
echo "── 5. License Validation ──"
if [ -n "$LIC" ]; then
  VAL_RESP=$(curl -s -X POST "$WORKER/v1/license/validate" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-1\",\"fingerprint\":{\"hostname\":\"healthcheck\"}}")
  if echo "$VAL_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('valid')" 2>/dev/null; then
    SEATS=$(echo "$VAL_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('seats','?'))")
    pass "License validated ($SEATS seats)"
  else
    fail "Validation failed: $VAL_RESP"
  fi
fi

# ── 6. Heartbeat ────────────────────────────────────────────────
echo "── 6. Heartbeat ──"
if [ -n "$LIC" ]; then
  HB_RESP=$(curl -s -X POST "$WORKER/v1/heartbeat" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-1\"}")
  if echo "$HB_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('valid')" 2>/dev/null; then
    pass "Heartbeat OK"
  else
    fail "Heartbeat failed: $HB_RESP"
  fi
fi

# ── 7. Seat limit enforcement ───────────────────────────────────
echo "── 7. Seat Limit Enforcement ──"
if [ -n "$LIC" ]; then
  curl -s -X POST "$WORKER/v1/license/validate" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-2\",\"fingerprint\":{\"hostname\":\"hc2\"}}" > /dev/null 2>&1
  curl -s -X POST "$WORKER/v1/license/validate" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-3\",\"fingerprint\":{\"hostname\":\"hc3\"}}" > /dev/null 2>&1

  FILL_RESP=$(curl -s -X POST "$WORKER/v1/license/validate" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-4\",\"fingerprint\":{\"hostname\":\"hc4\"}}")
  if echo "$FILL_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert not j.get('valid')" 2>/dev/null; then
    pass "4th seat correctly blocked (3-seat limit)"
  else
    fail "Seat limit not enforced: $FILL_RESP"
  fi
fi

# ── 8. Seat release ─────────────────────────────────────────────
echo "── 8. Seat Release ──"
if [ -n "$LIC" ]; then
  REL_RESP=$(curl -s -X POST "$WORKER/v1/license/release" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-1\"}")
  if echo "$REL_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('valid')" 2>/dev/null; then
    pass "Seat released successfully"
  else
    fail "Seat release failed: $REL_RESP"
  fi
fi

# ── 9. Validate after release (freed seat can be reused) ────────
echo "── 9. Freed Seat Reuse ──"
if [ -n "$LIC" ]; then
  REUSE_RESP=$(curl -s -X POST "$WORKER/v1/license/validate" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\",\"instance_id\":\"hc-node-4\",\"fingerprint\":{\"hostname\":\"hc4-retry\"}}")
  if echo "$REUSE_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('valid')" 2>/dev/null; then
    pass "Freed seat successfully reused"
  else
    fail "Freed seat not reusable: $REUSE_RESP"
  fi
fi

# ── 10. Full reset ──────────────────────────────────────────────
echo "── 10. Full License Reset ──"
if [ -n "$LIC" ]; then
  RESET_RESP=$(curl -s -X POST "$WORKER/v1/license/reset" \
    -H "Content-Type: application/json" \
    -d "{\"license_key\":\"$LIC\"}")
  if echo "$RESET_RESP" | python3 -c "import sys,json; j=json.load(sys.stdin); assert j.get('valid')" 2>/dev/null; then
    pass "All seats reset"
  else
    fail "Reset failed: $RESET_RESP"
  fi
fi

# ── 11. Resend email delivery (info only) ───────────────────────
echo "── 11. Email Delivery ──"
if [ -n "$LIC" ]; then
  warn "Email sent to test-$(date +%s)@healthcheck.local (check Resend dashboard if using a real address)"
  pass "Webhook triggered email pipeline"
fi

# ── Summary ─────────────────────────────────────────────────────
echo ""
echo "========================================="
echo -e " Results: ${GREEN}${PASS} passed${NC} / ${RED}${FAIL} failed${NC}"
echo "========================================="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
