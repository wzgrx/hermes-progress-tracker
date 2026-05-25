#!/usr/bin/env python3
"""
Manual progress push to hermes-feishu-streaming-card.

Usage:
    send_progress.py download 45 "Downloading model..."
    send_progress.py compile 100 "Build complete!"
    send_progress.py --message-id om_xxx download 60 "60% done" 120
    send_progress.py --title "Download Model" download 45 "45% done" 120
"""

import json
import os
import sys
import urllib.request

SIDECAR_BASE = os.environ.get("HERMES_SIDECAR_URL", "http://localhost:8765")


def main():
    args = sys.argv[1:]

    message_id = ""
    title = ""

    while args and args[0].startswith("--"):
        option = args[0]
        if option == "--message-id":
            if len(args) < 2:
                print("ERROR: --message-id requires a value", file=sys.stderr)
                sys.exit(1)
            message_id = args[1]
            args = args[2:]
        elif option == "--title":
            if len(args) < 2:
                print("ERROR: --title requires a value", file=sys.stderr)
                sys.exit(1)
            title = args[1]
            args = args[2:]
        else:
            print(f"ERROR: Unknown option {option}", file=sys.stderr)
            sys.exit(1)

    if len(args) < 2:
        print("Usage: send_progress.py [--message-id <id>] [--title <title>] <tool_name> <percent> [detail] [eta]",
              file=sys.stderr)
        sys.exit(1)

    tool_name = args[0]
    try:
        percent = int(args[1])
    except ValueError:
        print(f"ERROR: percent must be int, got '{args[1]}'", file=sys.stderr)
        sys.exit(1)

    detail = args[2] if len(args) > 2 else ""
    eta = int(args[3]) if len(args) > 3 and args[3].isdigit() else 0

    data = {
        "tool_id": tool_name,
        "percent": percent,
        "detail": detail,
        "eta": eta,
    }
    if message_id:
        data["message_id"] = message_id
    if title:
        data["title"] = title

    try:
        req = urllib.request.Request(
            f"{SIDECAR_BASE}/progress",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=5)
        result = json.loads(resp.read())
        if result.get("ok"):
            print(f"✅ {tool_name}: {percent}% pushed to card" +
                  (f" (title: {title})" if title else ""))
        else:
            print(f"⚠️  {result.get('error', 'unknown error')}")
    except Exception as e:
        print(f"❌ Failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
