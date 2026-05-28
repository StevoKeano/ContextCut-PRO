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
