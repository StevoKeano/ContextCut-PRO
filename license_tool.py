#!/usr/bin/env python3
"""
ContextCut PRO — License Seat Management Utility

Usage:
  python license_tool.py reset --key YOUR_LICENSE_KEY       Reset all seats for a license
  python license_tool.py status --key YOUR_LICENSE_KEY      Check active sessions
  python license_tool.py release --key YOUR_LICENSE_KEY --id INSTANCE_ID   Release one seat

Environment:
  CONTEXTCUT_LICENSE_SERVER  https://contextcut-license.ppsel03.workers.dev
"""

import os
import sys
import json
import argparse
import urllib.request

LICENSE_SERVER = os.getenv(
    "CONTEXTCUT_LICENSE_SERVER",
    "https://contextcut-license.ppsel03.workers.dev"
)

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "ContextCutPRO/1.0",
}


def api_call(path, data):
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{LICENSE_SERVER}{path}",
        data=payload,
        headers=HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def reset_license(license_key):
    result = api_call("/v1/license/reset", {"license_key": license_key})
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(f"OK: {result.get('message', 'Seats reset')}")


def release_seat(license_key, instance_id):
    result = api_call("/v1/license/release", {
        "license_key": license_key,
        "instance_id": instance_id,
    })
    if "error" in result:
        print(f"ERROR: {result['error']}")
        sys.exit(1)
    print(f"OK: {result.get('message', 'Seat released')}")


def main():
    parser = argparse.ArgumentParser(description="ContextCut PRO License Manager")
    parser.add_argument("--key", required=True, help="License key")
    sub = parser.add_subparsers(dest="action")

    reset_parser = sub.add_parser("reset", help="Reset all seats for this license")
    release_parser = sub.add_parser("release", help="Release a specific instance seat")
    release_parser.add_argument("--id", required=True, help="Instance ID to release")

    args = parser.parse_args()

    if args.action == "reset":
        reset_license(args.key)
    elif args.action == "release":
        release_seat(args.key, args.id)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
