#!/usr/bin/env python3
"""
ContextCut-PRO Factuality Test Runner

Sends queries with known ground truth to the proxy server and validates
responses for accuracy, hallucination detection, and citation correctness.

Usage:
    python3 run_tests.py                          # use default proxy (localhost:18788)
    python3 run_tests.py --proxy http://localhost:18788
    python3 run_tests.py --tests test_queries.json
    python3 run_tests.py --model "qwen3:14b-q8_0"
    python3 run_tests.py --verbose

Exit codes:
    0 = all tests passed
    1 = some tests failed
    2 = connection error / test harness failure
"""

import json
import re
import sys
import os
import time
import urllib.request
import urllib.error
import urllib.parse
import argparse
from typing import Any


# ── Colour helpers ─────────────────────────────────────────────────────────────
def green(s):
    return f"\033[92m{s}\033[0m"


def red(s):
    return f"\033[91m{s}\033[0m"


def yellow(s):
    return f"\033[93m{s}\033[0m"


def cyan(s):
    return f"\033[96m{s}\033[0m"


def bold(s):
    return f"\033[1m{s}\033[0m"


def dim(s):
    return f"\033[2m{s}\033[0m"


# ── Test query loader ──────────────────────────────────────────────────────────
def load_tests(path: str) -> list[dict]:
    with open(path, "r") as f:
        data = json.load(f)
    return data["tests"]


# ── Proxy interaction ──────────────────────────────────────────────────────────
def proxy_health_check(proxy_base: str) -> bool:
    try:
        req = urllib.request.Request(f"{proxy_base}/stats", method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def send_query(proxy_base: str, model: str, query: str, timeout: int = 60) -> dict:
    """Send a non-streaming chat completion request to the proxy.

    Returns a dict with keys: success (bool), content (str or None), error (str or None).
    """
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": query}],
        "stream": False,
        "session_id": f"test-session-{int(time.time())}",
    }).encode()

    req = urllib.request.Request(
        f"{proxy_base}/v1/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode("utf-8"))
            content = (
                resp.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {"success": True, "content": content, "error": None}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "content": None, "error": f"HTTP {e.code}: {err_body[:500]}"}
    except Exception as e:
        return {"success": False, "content": None, "error": str(e)}


# ── Response validation ────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    """Lowercase and collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def check_required_facts(content: str, facts: list[str]) -> tuple[list[str], list[str]]:
    """Returns (matched_facts, missing_facts)."""
    if not facts:
        return [], []
    norm = normalize(content)
    matched = []
    missing = []
    for fact in facts:
        # try exact phrase match first
        if normalize(fact) in norm:
            matched.append(fact)
        else:
            # try loose word-level matching (all significant words must appear within 20 words of each other)
            words = [w for w in normalize(fact).split() if len(w) > 2]
            if words and all(w in norm for w in words):
                matched.append(fact)
            else:
                missing.append(fact)
    return matched, missing


def check_forbidden_terms(content: str, terms: list[str]) -> list[str]:
    """Returns list of forbidden terms that were found in the response."""
    if not terms:
        return []
    norm = normalize(content)
    found = []
    for term in terms:
        if normalize(term) in norm:
            found.append(term)
    return found


def check_citations(content: str, citations: list[str]) -> tuple[list[str], list[str]]:
    """Returns (found_citations, missing_citations)."""
    if not citations:
        return [], []
    norm = normalize(content)
    found = []
    missing = []
    for cite in citations:
        if normalize(cite) in norm:
            found.append(cite)
        else:
            missing.append(cite)
    return found, missing


def is_entrapment_test(test: dict) -> bool:
    return test.get("category") == "entrapment"


def validate_entrapment(content: str, test: dict) -> tuple[bool, list[str]]:
    """Validate an entrapment/hallucination test.

    The LLM should:
    - Not fabricate the fake case/section
    - Either state it doesn't exist, or say it's not a real case, or refuse to answer

    Returns (passed, messages).
    """
    msgs = []
    forbidden = test.get("forbidden_terms", [])
    found_forbidden = check_forbidden_terms(content, forbidden)

    if found_forbidden:
        msgs.append(red(f"  HALLUCINATION: Fabricated term(s) appeared: {found_forbidden}"))
        return False, msgs

    # Check for appropriate refusal indicators
    refusal_indicators = [
        "does not exist",
        "not a real",
        "fabricated",
        "cannot find",
        "no record",
        "i don't know",
        "i'm not aware",
        "not a genuine",
        "do not have information",
        "cannot confirm",
        "no such case",
        "no such statute",
        "no such section",
        "not a valid",
        "appears to be",
        "not an actual",
        "there is no",
        "doesn't exist",
    ]
    norm = normalize(content)
    refused = any(indicator in norm for indicator in refusal_indicators)

    if refused:
        msgs.append(green("  Correctly avoided hallucination"))
        return True, msgs
    else:
        msgs.append(yellow("  WARNING: Did not explicitly refuse, but also did not hallucinate the fake term"))
        return True, msgs


def run_test(test: dict, proxy_base: str, model: str, verbose: bool) -> dict:
    """Run a single test. Returns result dict."""
    tid = test["id"]
    query = test["query"]
    required = test.get("required_facts", [])
    forbidden = test.get("forbidden_terms", [])
    citations = test.get("expected_citations", [])
    tolerance = test.get("tolerance", "moderate")
    is_trap = is_entrapment_test(test)

    if verbose:
        print(f"\n  Query: {query[:120]}...")

    result = send_query(proxy_base, model, query)
    if not result["success"]:
        return {
            "id": tid,
            "passed": False,
            "error": result["error"],
            "details": [red(f"  REQUEST FAILED: {result['error']}")],
            "response_preview": None,
        }

    content = result["content"] or ""
    response_preview = content[:300] + "..." if len(content) > 300 else content
    details = []

    if is_trap:
        trap_passed, trap_msgs = validate_entrapment(content, test)
        details.extend(trap_msgs)
        return {
            "id": tid,
            "passed": trap_passed,
            "error": None,
            "details": details,
            "response_preview": response_preview,
        }

    # Normal factuality test
    matched_facts, missing_facts = check_required_facts(content, required)
    found_forbidden = check_forbidden_terms(content, forbidden)
    found_citations, missing_citations = check_citations(content, citations)

    # Determine pass/fail based on tolerance
    if not required:
        facts_ok = True
    else:
        required_ratio = len(matched_facts) / len(required)
        if tolerance == "strict":
            facts_ok = len(missing_facts) == 0
        elif tolerance == "lenient":
            facts_ok = required_ratio >= 0.6
        else:  # moderate
            facts_ok = required_ratio >= 0.8

    forbidden_ok = len(found_forbidden) == 0
    citations_ok = len(missing_citations) == 0

    passed = facts_ok and forbidden_ok and citations_ok

    if missing_facts:
        details.append(red(f"  MISSING FACTS ({len(missing_facts)}):"))
        for f in missing_facts:
            details.append(red(f"    - {f}"))
    if matched_facts:
        details.append(green(f"  MATCHED FACTS ({len(matched_facts)}/{len(required)}):"))
        for f in matched_facts:
            details.append(green(f"    + {f}"))
    if found_forbidden:
        details.append(red(f"  FORBIDDEN TERMS FOUND ({len(found_forbidden)}):"))
        for f in found_forbidden:
            details.append(red(f"    ! {f}"))
    if missing_citations:
        details.append(red(f"  MISSING CITATIONS ({len(missing_citations)}):"))
        for c in missing_citations:
            details.append(red(f"    - {c}"))
    if found_citations:
        details.append(green(f"  FOUND CITATIONS ({len(found_citations)}/{len(citations)}):"))
        for c in found_citations:
            details.append(green(f"    + {c}"))

    if passed:
        details.append(green(f"  PASSED (tolerance={tolerance})"))
    else:
        reasons = []
        if not facts_ok:
            reasons.append(f"facts ({len(matched_facts)}/{len(required)})")
        if not forbidden_ok:
            reasons.append(f"forbidden terms found")
        if not citations_ok:
            reasons.append(f"citations ({len(found_citations)}/{len(citations)})")
        details.append(red(f"  FAILED: {' + '.join(reasons)}"))

    return {
        "id": tid,
        "passed": passed,
        "error": None,
        "details": details,
        "response_preview": response_preview,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="ContextCut-PRO Factuality Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_tests.py                              # defaults
  python3 run_tests.py --proxy http://localhost:18788
  python3 run_tests.py --model "qwen3:14b-q8_0"
  python3 run_tests.py --tests test_queries.json
  python3 run_tests.py --verbose
  python3 run_tests.py --filter discovery           # only test IDs containing 'discovery'
  python3 run_tests.py --entrapment-only            # only hallucination trap tests
        """,
    )
    parser.add_argument(
        "--proxy",
        default="http://localhost:18788",
        help="Proxy server base URL (default: http://localhost:18788)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name to use (default: auto-detect from proxy or use 'test-model')",
    )
    parser.add_argument(
        "--tests",
        default="test_queries.json",
        help="Path to test queries JSON file (default: test_queries.json)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show query text and full response previews",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="Only run tests whose ID contains this substring",
    )
    parser.add_argument(
        "--entrapment-only",
        action="store_true",
        help="Only run hallucination entrapment tests",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Timeout in seconds per query (default: 120)",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Seconds to wait between queries (default: 0, helps avoid rate limits)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate test file structure only — do not run queries",
    )
    parser.add_argument(
        "--show-tests",
        action="store_true",
        help="Print all test queries with their expected facts and exit",
    )

    args = parser.parse_args()
    proxy_base = args.proxy.rstrip("/")
    tests_path = args.tests

    # ── Load tests ─────────────────────────────────────────────────────────────
    if not os.path.exists(tests_path):
        print(red(f"ERROR: Test file not found: {tests_path}"))
        sys.exit(2)

    all_tests = load_tests(tests_path)
    print(cyan(f"\n  ContextCut-PRO Factuality Test Runner"))
    print(dim(f"  {'=' * 60}"))
    print(f"  Proxy:     {proxy_base}")
    print(f"  Tests:     {tests_path} ({len(all_tests)} total)")
    print(f"  Filter:    {args.filter or '(all)'}")
    print(dim(f"  {'=' * 60}"))

    # Apply filters
    tests = all_tests
    if args.entrapment_only:
        tests = [t for t in tests if is_entrapment_test(t)]
        print(f"  Mode:      entrapment-only ({len(tests)} tests)")
    elif args.filter:
        tests = [t for t in tests if args.filter.lower() in t["id"].lower()]
        print(f"  Filtered:  {len(tests)} tests match '{args.filter}'")

    if not tests:
        print(red(f"\n  ERROR: No tests match the given filter."))
        sys.exit(2)

    # ── Show-tests mode ────────────────────────────────────────────────────────
    if args.show_tests:
        print()
        for t in tests:
            tid = t["id"]
            print(f"  {bold(tid)}")
            print(f"    Query:        {t['query'][:100]}")
            if t.get("required_facts"):
                print(f"    Required:     {', '.join(t['required_facts'][:6])}")
                if len(t["required_facts"]) > 6:
                    print(f"                  ... and {len(t['required_facts'])-6} more")
            if t.get("forbidden_terms"):
                print(f"    Forbidden:    {', '.join(t['forbidden_terms'][:4])}")
                if len(t["forbidden_terms"]) > 4:
                    print(f"                  ... and {len(t['forbidden_terms'])-4} more")
            if t.get("expected_citations"):
                print(f"    Citations:    {', '.join(t['expected_citations'][:4])}")
            if t.get("note"):
                print(f"    Note:         {t['note']}")
            print()
        sys.exit(0)

    # ── Validate-only mode ─────────────────────────────────────────────────────
    if args.validate:
        print(f"\n  {cyan('Validating test file structure...')}\n")
        errors = []
        seen_ids = set()
        for i, t in enumerate(tests):
            tid = t.get("id", f"test-{i}")
            if not t.get("query"):
                errors.append(f"  [{tid}] Missing 'query' field")
            if not isinstance(t.get("required_facts", []), list):
                errors.append(f"  [{tid}] 'required_facts' must be a list")
            if not isinstance(t.get("forbidden_terms", []), list):
                errors.append(f"  [{tid}] 'forbidden_terms' must be a list")
            if t.get("tolerance") not in ("strict", "moderate", "lenient", None):
                errors.append(f"  [{tid}] 'tolerance' must be strict/moderate/lenient")
            if tid in seen_ids:
                errors.append(f"  [{tid}] Duplicate test ID")
            seen_ids.add(tid)

        if errors:
            print(red(f"  VALIDATION FAILED ({len(errors)} error(s)):"))
            for e in errors:
                print(f"  {e}")
            sys.exit(1)
        else:
            print(green(f"  All {len(tests)} tests validated OK"))
            print(f"  Categories: {sorted(set(t['category'] for t in tests))}")
            entrap = [t for t in tests if is_entrapment_test(t)]
            if entrap:
                print(f"  Entrapment tests: {len(entrap)}")
            sys.exit(0)

    # ── Health check ────────────────────────────────────────────────────────────
    print(f"\n  Checking proxy health at {proxy_base}/stats ...", end=" ")
    sys.stdout.flush()
    if not proxy_health_check(proxy_base):
        print(red("UNREACHABLE"))
        print()
        print(red(f"  Cannot connect to proxy at {proxy_base}."))
        print(yellow(f"  Make sure the proxy server is running:"))
        print(yellow(f"    python3 qdrant_proxy_final.py"))
        print(yellow(f"  Or specify a different URL:"))
        print(yellow(f"    python3 run_tests.py --proxy http://other-host:18788"))
        sys.exit(2)
    print(green("OK"))

    # ── Determine model ─────────────────────────────────────────────────────────
    model = args.model
    if not model:
        try:
            req = urllib.request.Request(f"{proxy_base}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                tags = json.loads(r.read().decode("utf-8"))
                models = [m["name"] for m in tags.get("models", [])]
                if models:
                    model = models[0]
                    print(f"  Auto-selected model: {model}")
        except Exception:
            model = "test-model"
            print(yellow(f"  Could not auto-detect model, using '{model}'"))

    # ── Run tests ───────────────────────────────────────────────────────────────
    results = []
    total = len(tests)
    passed_count = 0
    failed_count = 0
    trap_count = 0
    trap_passed = 0
    trap_failed = 0

    print()
    print(cyan(f"  Running {total} test(s)..."))
    print()

    for i, test in enumerate(tests, 1):
        tid = test["id"]
        is_trap = is_entrapment_test(test)
        label = f"[{i}/{total}] {tid}"

        if is_trap:
            label += " " + yellow("(entrapment)")

        print(f"  {bold(label)}")
        sys.stdout.flush()

        start = time.time()
        result = run_test(test, proxy_base, model, args.verbose)
        elapsed = time.time() - start

        for line in result["details"]:
            print(f"  {line}")

        if args.verbose and result["response_preview"]:
            print(dim(f"  Response preview: {result['response_preview'][:200]}"))

        print(dim(f"  ({elapsed:.1f}s)"))
        print()

        if is_trap:
            trap_count += 1
            if result["passed"]:
                trap_passed += 1
            else:
                trap_failed += 1

        if result["passed"]:
            passed_count += 1
        else:
            failed_count += 1

        results.append(result)

        if args.wait > 0 and i < total:
            print(dim(f"  Waiting {args.wait}s..."))
            time.sleep(args.wait)

    # ── Summary ─────────────────────────────────────────────────────────────────
    print(cyan(f"  {'=' * 60}"))
    total_checks = passed_count + failed_count
    pct = (passed_count / total_checks * 100) if total_checks else 0
    print(f"  {bold('SUMMARY')}")
    print(dim(f"  {'=' * 60}"))
    print(f"  Total:     {total_checks}")
    print(f"  {green('Passed')}:    {passed_count}")
    print(f"  {red('Failed')}:    {failed_count}")
    print(f"  Score:     {pct:.1f}%")

    if trap_count > 0:
        trap_pct = (trap_passed / trap_count * 100) if trap_count else 0
        print(f"  {yellow('Entrapment')}: {trap_passed}/{trap_count} passed ({trap_pct:.1f}%)")
        if trap_failed > 0:
            print(red(f"    WARNING: LLM hallucinated {trap_failed} fabricated case(s)/statute(s)!"))

    print()

    if passed_count == total_checks:
        print(green(f"  {'=' * 60}"))
        print(green(f"  ALL TESTS PASSED"))
        print(green(f"  {'=' * 60}"))
        sys.exit(0)
    elif failed_count > 0:
        print(red(f"  {'=' * 60}"))
        print(red(f"  {failed_count} TEST(S) FAILED — review details above"))
        print(red(f"  {'=' * 60}"))
        sys.exit(1)
    else:
        print(yellow(f"  No tests were executed."))
        sys.exit(0)


if __name__ == "__main__":
    main()
