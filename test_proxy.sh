#!/bin/bash
# ContextCut proxy test suite
# Run from Ubuntu: bash test_proxy.sh

PROXY="http://127.0.0.1:18788"
DASH="http://127.0.0.1:18787"
UPSTREAM="http://192.168.1.101:11434"
PASS=0; FAIL=0

ok()   { echo "PASS  $1"; PASS=$((PASS+1)); }
fail() { echo "FAIL  $1"; FAIL=$((FAIL+1)); }
sep()  { echo ""; echo "── $1 ──────────────────────────────────"; }

sep "1. Processes"
pgrep -f qdrant_proxy.py > /dev/null && ok "proxy process running" || fail "proxy process NOT running"

sep "2. Ports"
lsof -i :18787 | grep -q LISTEN && ok "port 18787 listening" || fail "port 18787 NOT listening"
lsof -i :18788 | grep -q LISTEN && ok "port 18788 listening" || fail "port 18788 NOT listening"

sep "3. Upstream Ollama reachable"
curl -sf --max-time 5 "$UPSTREAM/api/tags" > /dev/null && ok "Ollama reachable at $UPSTREAM" || fail "Ollama NOT reachable at $UPSTREAM"

sep "4. Qdrant reachable"
QDRANT_HOST=$(grep QDRANT_HOST ~/contextcut/.env | cut -d= -f2)
curl -sf --max-time 5 "http://$QDRANT_HOST:6333/collections" > /dev/null && ok "Qdrant reachable" || fail "Qdrant NOT reachable"

sep "5. Dashboard loads"
curl -sf --max-time 5 "$DASH" | grep -q "ContextCut" && ok "dashboard HTML loads" || fail "dashboard NOT loading"

sep "6. /stats endpoint"
STATS=$(curl -sf --max-time 5 "$DASH/stats")
echo "$STATS" | python3 -m json.tool > /dev/null 2>&1 && ok "/stats returns valid JSON" || fail "/stats NOT returning JSON"
echo "     $STATS"

sep "7. /log endpoint"
LOG=$(curl -sf --max-time 5 "$DASH/log")
echo "$LOG" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  entries: {len(d)}')" 2>/dev/null && ok "/log returns valid JSON" || fail "/log NOT returning JSON"

sep "8. /api/tags passthrough (model list)"
TAGS=$(curl -sf --max-time 10 "$DASH/api/tags")
if echo "$TAGS" | python3 -c "import sys,json; d=json.load(sys.stdin); models=[m['name'] for m in d.get('models',[])]; print('\n'.join(f'  {m}' for m in models[:5])); exit(0 if models else 1)" 2>/dev/null; then
  ok "/api/tags returns model list"
else
  fail "/api/tags NOT returning models (DDL will be empty)"
  echo "  Raw response: ${TAGS:0:200}"
fi

sep "9. Proxy injection test (direct to proxy port)"
MODEL=$(curl -sf --max-time 5 "$UPSTREAM/api/tags" | python3 -c "
import sys, json
models = [m['name'] for m in json.load(sys.stdin).get('models', [])]
# prefer known good local model
preferred = 'qwen3:14b-q8_0'
if preferred in models:
    print(preferred)
else:
    # fall back to first model not containing 'cloud'
    local = [m for m in models if 'cloud' not in m.lower()]
    print(local[0] if local else models[0])
" 2>/dev/null)
echo "  Using model: $MODEL"
RESP=$(curl -sf --max-time 60 -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"what are the guardrails\"}],\"model\":\"$MODEL\"}")
if echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); t=d['usage']['prompt_tokens']; print(f'  prompt_tokens: {t}'); exit(0 if t>20 else 1)" 2>/dev/null; then
  ok "proxy injection working (tokens > 20)"
else
  fail "proxy injection NOT working — likely 0 context injected"
  echo "  Raw: ${RESP:0:300}"
fi

sep "10. Dashboard send (simulates chat UI fetch)"
DASH_RESP=$(curl -sf --max-time 60 -X POST "$DASH/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"model\":\"$MODEL\"}")
if echo "$DASH_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  content: {d[\"choices\"][0][\"message\"][\"content\"][:80]}'); exit(0)" 2>/dev/null; then
  ok "dashboard POST /v1/chat/completions works"
else
  fail "dashboard POST /v1/chat/completions FAILED"
  echo "  Raw: ${DASH_RESP:0:300}"
fi
sep "11. Streaming response test"
STREAM=$(curl -sf --max-time 30 -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"say hi\"}],\"model\":\"$MODEL\",\"stream\":true}" \
  --no-buffer 2>&1 | head -5)
if echo "$STREAM" | grep -q "data:"; then
  ok "streaming returns SSE data: chunks"
else
  fail "streaming NOT returning SSE chunks"
  echo "  Raw: ${STREAM:0:200}"
fi

sep "12. MIN_SCORE threshold filtering"
MIN=$(grep CONTEXTCUT_MIN_SCORE ~/contextcut/.env | cut -d= -f2)
echo "  Configured MIN_SCORE: $MIN"
RESP=$(curl -sf --max-time 60 -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"what are the guardrails\"}],\"model\":\"$MODEL\"}")
PTOK=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['usage']['prompt_tokens'])" 2>/dev/null)
echo "  prompt_tokens with threshold $MIN: $PTOK"
[ "${PTOK:-0}" -gt 20 ] && ok "threshold filtering: relevant chunks injected ($PTOK tokens)" || fail "threshold filtering: nothing injected"

sep "13. Off-topic query — no injection (below threshold)"
RESP2=$(curl -sf --max-time 60 -X POST "$PROXY/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"explain quantum entanglement\"}],\"model\":\"$MODEL\"}")
PTOK2=$(echo "$RESP2" | python3 -c "import sys,json; print(json.load(sys.stdin)['usage']['prompt_tokens'])" 2>/dev/null)
echo "  prompt_tokens for off-topic query: $PTOK2"
[ "${PTOK2:-9999}" -lt 50 ] && ok "off-topic: no injection ($PTOK2 tokens — below threshold)" || fail "off-topic: context injected when it shouldn't be ($PTOK2 tokens)"

sep "14. Context usage below 25%"
STATS2=$(curl -sf --max-time 5 "$DASH/stats")
PCT=$(echo "$STATS2" | python3 -c "import sys,json; print(json.load(sys.stdin)['pct'])" 2>/dev/null)
CTX=$(grep CONTEXTCUT_CTX_LIMIT ~/contextcut/.env | cut -d= -f2)
echo "  Context: ${PCT}% of ${CTX} token limit"
python3 -c "exit(0 if float('${PCT:-0}') < 25 else 1)" 2>/dev/null && ok "context usage ${PCT}% is below 25%" || fail "context usage ${PCT}% EXCEEDS 25% limit"

sep "15. /log reflects last request"
LOG2=$(curl -sf --max-time 5 "$DASH/log")
LOGCOUNT=$(echo "$LOG2" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
LOGHITS=$(echo "$LOG2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d[0]['hits']) if d else 0)" 2>/dev/null)
echo "  Log entries: $LOGCOUNT  Hits on last request: $LOGHITS"
[ "${LOGCOUNT:-0}" -gt 0 ] && ok "/log has $LOGCOUNT entries" || fail "/log is empty after requests"
[ "${LOGHITS:-0}" -gt 0 ] && ok "last request had $LOGHITS Qdrant hit(s)" || fail "last request had 0 Qdrant hits"

sep "16. Model DDL endpoint (/api/tags from dashboard port)"
TAGS2=$(curl -sf --max-time 10 "$DASH/api/tags")
MCOUNT=$(echo "$TAGS2" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null)
echo "  Models available: $MCOUNT"
[ "${MCOUNT:-0}" -gt 0 ] && ok "/api/tags returns $MCOUNT models for DDL" || fail "/api/tags returned no models — DDL will be empty"

sep "17. Dashboard POST /v1/chat/completions (Send button path)"
DRESP=$(curl -sf --max-time 60 -X POST "$DASH/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"what are the guardrails\"}],\"model\":\"$MODEL\"}")
DPTOK=$(echo "$DRESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['usage']['prompt_tokens'])" 2>/dev/null)
DCONT=$(echo "$DRESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['message']['content'][:60])" 2>/dev/null)
echo "  prompt_tokens: $DPTOK"
echo "  response: $DCONT"
[ "${DPTOK:-0}" -gt 20 ] && ok "Send button path working with injection ($DPTOK tokens)" || fail "Send button path FAILED or no injection"

sep "Summary"
echo "  PASS: $PASS   FAIL: $FAIL"
echo ""
