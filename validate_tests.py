#!/usr/bin/env python3
"""
ContextCut-PRO Test Data Integrity Validator

Cross-references the test queries against the actual knowledge base source files
to ensure the "known answers" (required_facts, expected_citations) are accurate.

Usage:
    python3 validate_tests.py
    python3 validate_tests.py --tests test_queries.json --knowledge-dir starterKnowledgeFiles
"""

import json
import os
import sys
import re
import argparse
from pathlib import Path


def green(s):
    return f"\033[92m{s}\033[0m"


def red(s):
    return f"\033[91m{s}\033[0m"


def yellow(s):
    return f"\033[93m{s}\033[0m"


def bold(s):
    return f"\033[1m{s}\033[0m"


def load_tests(path: str) -> list[dict]:
    with open(path, "r") as f:
        data = json.load(f)
    return data["tests"]


def validate_test_against_source(
    test: dict, source_dir: str
) -> list[str]:
    """Validate each required_fact and citation against source files.

    Returns a list of warning messages.
    """
    warnings = []
    source_files = test.get("source_files", [])
    facts = test.get("required_facts", [])
    citations = test.get("expected_citations", [])

    if not source_files:
        return warnings  # entrapment tests have no source files

    # Load all source content
    source_texts = {}
    for sf in source_files:
        path = os.path.join(source_dir, sf)
        if os.path.exists(path):
            with open(path, "r") as f:
                source_texts[sf] = f.read()
        else:
            warnings.append(red(f"  Source file not found: {sf}"))

    all_source_text = "\n".join(source_texts.values()).lower()

    for fact in facts:
        fact_lower = fact.lower()
        # Check if this fact appears in any source file
        found = fact_lower in all_source_text
        if not found:
            # Try word-level matching
            words = [w for w in fact_lower.split() if len(w) > 3]
            if words:
                found = all(w in all_source_text for w in words)

        if not found:
            warnings.append(
                yellow(f"  Fact may not be directly in sources: '{fact}'")
            )

    for citation in citations:
        citation_lower = citation.lower()
        if citation_lower not in all_source_text:
            warnings.append(
                yellow(f"  Citation may not be directly in sources: '{citation}'")
            )

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Validate test data integrity against knowledge base source files"
    )
    parser.add_argument(
        "--tests",
        default="test_queries.json",
        help="Path to test queries JSON file (default: test_queries.json)",
    )
    parser.add_argument(
        "--knowledge-dir",
        default="starterKnowledgeFiles",
        help="Directory containing knowledge base source .md files",
    )
    args = parser.parse_args()

    if not os.path.exists(args.tests):
        print(red(f"ERROR: Test file not found: {args.tests}"))
        sys.exit(1)

    if not os.path.isdir(args.knowledge_dir):
        print(red(f"ERROR: Knowledge directory not found: {args.knowledge_dir}"))
        sys.exit(1)

    tests = load_tests(args.tests)
    print(f"\n  {bold('Test Data Integrity Check')}")
    print(f"  Tests:      {args.tests} ({len(tests)} total)")
    print(f"  Knowledge:  {args.knowledge_dir}")
    print()

    all_warnings = []
    validation_passed = []
    validation_failed = []

    for t in tests:
        tid = t["id"]
        is_trap = t.get("category") == "entrapment"
        if is_trap:
            print(f"  {bold(tid)} {yellow('(entrapment — skipped)')}")
            continue

        label = f"  {bold(tid)}"
        source_files = t.get("source_files", [])
        print(label)

        if source_files:
            for sf in source_files:
                sf_path = os.path.join(args.knowledge_dir, sf)
                exists = os.path.exists(sf_path)
                status = green("✓") if exists else red("✗")
                print(f"    Source:  {status} {sf}")

        warnings = validate_test_against_source(t, args.knowledge_dir)
        if warnings:
            validation_failed.append(tid)
            all_warnings.extend(warnings)
            for w in warnings:
                print(f"    {w}")
        else:
            validation_passed.append(tid)
            print(f"    {green('All required facts verified against source files')}")

        print()

    # Summary
    print(f"  {bold('Summary')}")
    print(f"  Passed: {len(validation_passed)}")
    print(f"  Warnings: {len(validation_failed)}")
    if all_warnings:
        print()
        print(yellow("  Notes:"))
        print(yellow("  - Warnings indicate facts that may use different wording"))
        print(yellow("    than the source file. Review manually to ensure accuracy."))
        print(yellow("  - The test runner uses fuzzy matching (case-insensitive,"))
        print(yellow("    partial word matching), so these may still pass."))

    return 0 if len(validation_failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
