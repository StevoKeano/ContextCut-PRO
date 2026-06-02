# ContextCut-PRO — Agent instructions

## Working dir
`E:\dev\opencode\ContextCut-PRO` (WSL: `/mnt/e/dev/opencode/ContextCut-PRO`)

## Deploy workflow
After editing files:

1. **Copy to user's repo:**
   ```bash
   cp /mnt/e/dev/opencode/ContextCut-PRO/{filename} /mnt/e/Dev/contextcut-pro/{filename}
   ```

2. **Provide git commands** (user runs from `E:\Dev\contextcut-pro`):
   ```
   git add {files}
   git commit -m "message"
   git push
   ```

3. **Provide SCP command** (user runs from Windows cmd):
   ```
   scp {filename} steve@192.168.137.252:~/contextcut/{filename}
   ```

## Ingestion (ingest.py)

Qdrant knowledge base ingestion tool. Ingest files from `KB_DIR` (default `~/contextcut/knowledge`).

| Mode | Command | Behavior |
|---|---|---|
| One-shot | `python3 ingest.py` | Ingest all files from KB_DIR |
| Watch | `python3 ingest.py --watch` | `ingest_all()` then watch for changes |
| Clear | `python3 ingest.py --clear` | Delete the Qdrant collection |

### Watcher event handling

The `Handler` class in `watch()` handles these events:
- `on_created` — new files
- `on_modified` — edits
- `on_moved` — bulk moves into KB_DIR (was missing — the root cause of missed files)
- `on_any_event` — catch-all for `closed` events (some editors use temp-file + rename)
- `on_deleted` — removes all chunks with matching filename from Qdrant

Debounce: **5s** (was 30s — reduced for rapid bulk ops). Observer runs with `recursive=False`.

### Deploy after editing ingest.py

1. **Copy to user's repo:**
   ```bash
   cp /mnt/e/dev/opencode/ContextCut-PRO/ingest.py /mnt/e/Dev/contextcut-pro/ingest.py
   ```

2. **SCP to proxy** (from Windows cmd at `E:\Dev\contextcut-pro`):
   ```
   scp ingest.py steve@192.168.137.252:~/contextcut/ingest.py
   ```

3. **Restart watcher on proxy**:
   ```bash
   kill $(pgrep -f "ingest.py --watch")
   python3 ~/contextcut/ingest.py --clear
   python3 ~/contextcut/ingest.py --watch &
   ```

## Factuality Test Suite

Three files implement an automated hallucination/accuracy test system:

| File | Purpose |
|---|---|
| `test_queries.json` | 18 test queries (15 factual + 3 entrapment) with known ground truth |
| `run_tests.py` | Automated runner — sends queries to proxy, validates responses |
| `validate_tests.py` | Integrity checker — verifies test facts against source knowledge files |

**Usage** (run on the machine with the proxy server):
```bash
# Show all test details (for tester to review ground truth)
python3 run_tests.py --show-tests

# Validate test structure without running
python3 run_tests.py --validate

# Cross-reference test facts against source files
python3 validate_tests.py

# Run ALL tests against a local proxy
python3 run_tests.py

# Run against a remote proxy
python3 run_tests.py --proxy http://192.168.137.252:18787

# Specify a model, wait between queries
python3 run_tests.py --model "qwen3:14b-q8_0" --wait 2

# Only run hallucination entrapment tests
python3 run_tests.py --entrapment-only

# Filter by domain
python3 run_tests.py --filter discovery
python3 run_tests.py --filter zoning
python3 run_tests.py --filter qbi

# Verbose mode (show queries + response previews)
python3 run_tests.py --verbose

# Quick connectivity check only
python3 run_tests.py --ping

# Increase timeout for large models (default 300s)
python3 run_tests.py --timeout 600
```

The test runner connects to the proxy's `/v1/chat/completions` endpoint, posts each query (non-streaming), and validates the response against **required_facts**, **forbidden_terms**, and **expected_citations**. Three entrapment tests use fabricated cases/statutes to detect hallucination. Each fact re-check uses fuzzy matching (case-insensitive, word-level, and exact phrase matching).

## Constraints
- NEVER git commit/push from own directory.
- NEVER touch files outside `/mnt/e/dev/opencode/ContextCut-PRO` without asking.
- Only provide commands for user to run.
