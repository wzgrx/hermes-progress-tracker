#!/usr/bin/env python3
"""
Auto Progress Monitor — wraps any long-running command, detects percentage
progress from output, and pushes updates to hermes-feishu-streaming-card.

Usage:
    auto_progress.py --tool download -- wget -c <url> -O file
    auto_progress.py --tool compile --interval 5 -- make -j16
    auto_progress.py --tool install -- python3 setup.py build

The script runs the command as a subprocess, scans stdout/stderr for
percentage patterns every N seconds, and POSTs progress to the streaming
card sidecar at http://localhost:18900/progress.

Supported progress formats (auto-detected via regex):
  - " 45%" (wget, cmake, ninja)
  - "[ 55%]" / "[55%]" (make, GCC compilation)
  - "### 45.0%" (pip, setuptools)
  - "45/100" / "45/100 files" (rsync, generic counters)
  - "45.2 MB / 100.0 MB" (curl, generic download)

When no progress pattern is found, sends heartbeat updates every 30s.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# --- Config ---
SIDECAR_BASE = os.environ.get("HERMES_SIDECAR_URL", "http://localhost:18900")
DEFAULT_INTERVAL = 5  # seconds between checks
HEARTBEAT_INTERVAL = 30  # seconds between heartbeats when no progress found
PROGRESS_PATTERNS = [
    # wget: " 45% ", "100%"
    re.compile(r'\b(\d{1,3})%\s'),
    # make/cmake: "[ 45%]" or "[45%]"
    re.compile(r'\[\s*(\d{1,3})%\]'),
    # pip: "### 45.0%"
    re.compile(r'###\s*(\d{1,3}(?:\.\d)?)%'),
    # scp/rsync: "45%" 
    re.compile(r'^\s*(\d{1,3})%\s+'),
    # Generic counter: "45/100" or "45/100 files" or "45/100MB"
    re.compile(r'(\d{1,5})\s*/\s*(\d{1,5})\s*(?:files?|MB|KB|GB)?\s'),
    # curl download: "45.2 MB / 100.0 MB"
    re.compile(r'(\d+\.?\d*)\s*(?:MB|KB|GB)\s*/\s*\d+\.?\d*\s*(?:MB|KB|GB)'),
]


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Auto Progress Monitor")
    parser.add_argument("--tool", default="command", help="Tool name for card display")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help=f"Check interval in seconds (default: {DEFAULT_INTERVAL})")
    parser.add_argument("--message-id", default="", help="Optional message ID for card targeting")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")
    args = parser.parse_args()
    if not args.command:
        # Handle case where command is after --
        remaining = [a for a in sys.argv[1:] if a != '--']
        # Re-parse
        idx = len(sys.argv) - len(remaining)
        args = parser.parse_args(sys.argv[1:idx] + ['--'] + remaining)
    return args


def extract_progress(line: str) -> int | None:
    """Return progress percentage (0-100) or None."""
    for pattern in PROGRESS_PATTERNS:
        m = pattern.search(line)
        if m:
            if pattern == PROGRESS_PATTERNS[4]:  # counter pattern: X/Y
                total = int(m.group(2))
                if total > 0:
                    return min(100, int(int(m.group(1)) * 100 / total))
            elif pattern == PROGRESS_PATTERNS[5]:  # curl: X MB / Y MB
                parts = line.split('/')
                if len(parts) >= 2:
                    try:
                        done = float(m.group(1))
                        total_str = re.search(r'/\s*(\d+\.?\d*)', line)
                        if total_str:
                            total = float(total_str.group(1))
                            if total > 0:
                                return min(100, int(done * 100 / total))
                    except ValueError:
                        pass
            else:
                pct = int(m.group(1))
                return min(100, pct)
    return None


def push_progress(tool_name: str, percent: int, detail: str = "", eta: int = 0, message_id: str = ""):
    """Push progress update to sidecar."""
    data = {
        "tool_id": tool_name,
        "percent": percent,
        "detail": detail,
        "eta": eta,
    }
    if message_id:
        data["message_id"] = message_id
    try:
        req = urllib.request.Request(
            f"{SIDECAR_BASE}/progress",
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        # Sidecar might not be running — silent failure
        pass


def run_with_progress(args):
    """Run command and monitor output for progress."""
    if not args.command:
        print("ERROR: No command specified", file=sys.stderr)
        sys.exit(1)
    
    cmd = args.command
    if cmd[0] == '--':
        cmd = cmd[1:]
    
    tool_name = args.tool
    interval = max(1, min(args.interval, 60))
    message_id = args.message_id
    
    # Start the subprocess
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except FileNotFoundError as e:
        print(f"ERROR: Command not found: {e}", file=sys.stderr)
        sys.exit(1)
    
    last_progress = -1
    last_heartbeat = 0
    last_logged_progress = ""
    start_time = time.time()
    output_lines = []
    
    # Push initial progress
    push_progress(tool_name, 0, "Starting...", message_id=message_id)
    
    # Read output line by line
    for line in iter(proc.stdout.readline, ''):
        output_lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
        
        # Extract progress
        pct = extract_progress(line)
        now = time.time()
        elapsed = int(now - start_time)
        
        if pct is not None and pct != last_progress:
            last_progress = pct
            last_logged_progress = line.strip()[:60]
            # Estimate ETA based on elapsed
            eta = int(elapsed * (100 - pct) / max(pct, 1)) if pct > 0 else 0
            push_progress(tool_name, pct, last_logged_progress, eta, message_id)
        elif pct is None and (now - last_heartbeat) > HEARTBEAT_INTERVAL:
            # Heartbeat — still running
            last_heartbeat = now
            last_logged_progress = f"Running... ({elapsed}s elapsed)"
            push_progress(tool_name, -1, last_logged_progress, message_id=message_id)
    
    # Wait for process to finish
    proc.wait()
    
    # Push completion
    exit_code = proc.returncode
    push_progress(tool_name, 100, f"Completed (exit={exit_code})", message_id=message_id)
    
    # Print final output
    for line in proc.stdout:
        output_lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()
    
    elapsed = int(time.time() - start_time)
    print(f"\n--- Auto Progress: {tool_name} completed in {elapsed}s (exit={exit_code}) ---")
    
    return exit_code


def main():
    args = parse_args()
    if not args.command:
        print("Usage: auto_progress.py --tool <name> [--interval N] [-- <command>]", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_with_progress(args))


if __name__ == "__main__":
    main()
