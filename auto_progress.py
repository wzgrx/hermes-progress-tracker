#!/usr/bin/env python3
"""
Auto Progress Monitor — wraps any long-running command, detects percentage
progress from output, and pushes updates to hermes-feishu-streaming-card.

Usage:
    auto_progress.py --tool download -- wget -c <url> -O file
    auto_progress.py --tool compile --interval 5 -- make -j16
    auto_progress.py --tool install -- python3 setup.py build
    auto_progress.py --foreground --tool download -- wget -c <url>

The script runs the command as a subprocess, scans stdout/stderr for
percentage patterns every N seconds, and POSTs progress to the streaming
card sidecar at http://localhost:8765/progress.

Supported progress formats:
  - " 45%" (wget, cmake, ninja, dd)
  - "[ 55%]" / "[55%]" (make, GCC compilation)
  - "### 45.0%" (pip, setuptools)
  - "45/100" / "45/100 files" (rsync, generic counters)
  - "45.2 MB / 100.0 MB" (curl, generic download)
  - "Receiving objects:  45%" (git clone)
  - "#45.0%" (conda)
  - "Progress: [###  >   ] 45%" (apt, apt-get)
  - "size=  45MB  rate=..." (dd status=progress)
  - "frame=  45 fps=..." (ffmpeg)

When no progress pattern is found, sends heartbeat updates every 30s.
Foreground mode (--foreground): prints progress to stdout for CLI use.
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
SIDECAR_BASE = os.environ.get("HERMES_SIDECAR_URL", "http://localhost:8765")
DEFAULT_INTERVAL = 5  # seconds between checks
HEARTBEAT_INTERVAL = 30  # seconds between heartbeats when no progress found
PROGRESS_PATTERNS = [
    # pip: "### 45.0%" — most specific, match before generic
    re.compile(r'###\s*(\d{1,3}(?:\.\d)?)%'),
    # conda: "#45.0%"
    re.compile(r'#\s*(\d{1,3}(?:\.\d)?)%'),
    # apt: "Progress: [###  >   ] 45%"
    re.compile(r'Progress:.*?(\d{1,3})%'),
    # git clone: "Receiving objects:  45%"
    re.compile(r'(?:Receiving|Resolving|Compressing|Checking)\s+.*?(\d{1,3})%'),
    # make/cmake: "[ 45%]" or "[45%]"
    re.compile(r'\[\s*(\d{1,3})%\]'),
    # scp/rsync: "45%" at line start
    re.compile(r'^\s*(\d{1,3})%\s+'),
    # wget/generic: " 45% " — use negative lookbehind to avoid matching ".0%"
    re.compile(r'(?<!\d\.)\b(\d{1,3})%\s'),
    # ffmpeg: "frame= 45 fps=..."
    re.compile(r'frame=\s*(\d+)'),
    # dd: "size=  45MB  rate=..."
    re.compile(r'size\s*=\s*(\d+\.?\d*)\s*(?:MB|KB|GB)'),
    # Generic counter: "45/100" or "45/100 files" or "45/100MB"
    re.compile(r'(\d{1,5})\s*/\s*(\d{1,5})\s*(?:files?|MB|KB|GB)?(?:\s|$|\b)'),
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
    parser.add_argument("--foreground", action="store_true",
                        help="Print progress bar to stdout for CLI use")
    parser.add_argument("--title", default="", help="Card header title when progress is running")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run")
    args = parser.parse_args()
    if not args.command:
        remaining = [a for a in sys.argv[1:] if a != '--']
        idx = len(sys.argv) - len(remaining)
        args = parser.parse_args(sys.argv[1:idx] + ['--'] + remaining)
    return args


def extract_progress(line: str) -> int | None:
    """Return progress percentage (0-100) or None."""
    for pattern in PROGRESS_PATTERNS:
        m = pattern.search(line)
        if m:
            if pattern == PROGRESS_PATTERNS[9]:  # counter pattern: X/Y
                total = int(m.group(2))
                if total > 0:
                    return min(100, int(int(m.group(1)) * 100 / total))
            elif pattern == PROGRESS_PATTERNS[10]:  # curl: X MB / Y MB
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
            elif pattern == PROGRESS_PATTERNS[7]:  # ffmpeg: frame=N
                return None
            elif pattern == PROGRESS_PATTERNS[8]:  # dd: size=  X MB
                # Estimate progress from total size — needs input size context
                return None
            else:
                pct = int(float(m.group(1)))
                return min(100, pct)
    return None


def push_progress(tool_name: str, percent: int, detail: str = "",
                  eta: int = 0, message_id: str = "", title: str = ""):
    """Push progress update to sidecar."""
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
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


def format_progress_bar(percent: int, width: int = 12) -> str:
    """Render a text progress bar like ████████░░░ 60%"""
    filled = percent * width // 100
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {percent:3d}%"


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
    is_foreground = args.foreground
    title = args.title

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
    push_progress(tool_name, 0, "Starting...", message_id=message_id, title=title)
    if is_foreground:
        print(f"\n⏳ [{tool_name}] Starting...")

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
            push_progress(tool_name, pct, last_logged_progress, eta, message_id, title)
            if is_foreground:
                bar = format_progress_bar(pct)
                print(f"\r{bar} ETA {eta}s", end="", file=sys.stderr)
                sys.stderr.flush()
        elif pct is None and (now - last_heartbeat) > HEARTBEAT_INTERVAL:
            # Heartbeat — still running
            last_heartbeat = now
            last_logged_progress = f"Running... ({elapsed}s elapsed)"
            push_progress(tool_name, -1, last_logged_progress, message_id=message_id, title=title)
            if is_foreground:
                print(f"\r⏳ Running... ({elapsed}s elapsed)", end="", file=sys.stderr)
                sys.stderr.flush()

    # Wait for process to finish
    proc.wait()

    # Push completion
    exit_code = proc.returncode
    push_progress(tool_name, 100, f"Completed (exit={exit_code})", message_id=message_id, title=title)
    if is_foreground:
        status = "✅" if exit_code == 0 else "❌"
        print(f"\n{status} [{tool_name}] Completed (exit={exit_code})", file=sys.stderr)

    # Read remaining output
    for line in proc.stdout:
        output_lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()

    elapsed = int(time.time() - start_time)
    final_status = "completed" if exit_code == 0 else f"failed (exit={exit_code})"
    print(f"\n--- Auto Progress: {tool_name} {final_status} in {elapsed}s ---")

    return exit_code


def detect_long_command(args) -> bool:
    """Check if a command is a long-running type that benefits from progress tracking.
    
    Returns True for: wget, curl, make, cmake, pip, pip3, git, conda, apt,
    apt-get, dd, rsync, ffmpeg, ninja, python3 setup.py, npm install, cargo build
    """
    if not args.command:
        return False
    cmd = args.command[0] if args.command[0] != '--' else (args.command[1] if len(args.command) > 1 else '')
    base = os.path.basename(cmd)
    
    long_cmds = {
        'wget', 'curl', 'make', 'cmake', 'ninja',
        'pip', 'pip3', 'pip3.14',
        'git', 'conda', 'apt', 'apt-get', 'aptitude',
        'dd', 'rsync', 'ffmpeg',
        'npm', 'cargo', 'bun', 'yarn', 'pnpm',
    }
    if base in long_cmds:
        return True
    # python3 setup.py build/install
    if base == 'python3' and len(args.command) > 1 and args.command[1] in ('setup.py', '-m'):
        return True
    return False


def auto_wrap_command(raw_command: str, tool_name: str = "") -> str:
    """Wrap a command string with auto_progress if it's a long-running type.
    
    Args:
        raw_command: The original command string
        tool_name: Optional tool name override (auto-detected from base command)
    
    Returns:
        The wrapped command if applicable, or the original command unchanged.
    """
    key_cmds = {
        'wget', 'curl', 'make', 'cmake', 'ninja',
        'pip', 'pip3', 'pip3.14',
        'git clone', 'conda install', 'conda create',
        'apt', 'apt-get',
        'dd', 'rsync',
        'ffmpeg',
        'npm install', 'npm ci',
        'cargo build', 'cargo test',
    }
    
    if not raw_command:
        return raw_command
    
    lower = raw_command.strip().lower()
    detected_tool = tool_name
    
    # Detect tool name from command
    for cmd in sorted(key_cmds, key=len, reverse=True):
        if lower.startswith(cmd):
            if not detected_tool:
                detected_tool = cmd.split()[0]
            break
    
    if not detected_tool:
        return raw_command  # Not a tracked command
    
    # Escape single quotes for shell
    escaped_cmd = raw_command.replace("'", "'\\''")
    script_path = os.path.expanduser("~/.hermes/scripts/auto_progress.py")
    return (
        f"python3 '{script_path}' "
        f"--tool '{detected_tool}' "
        f"-- '{escaped_cmd}'"
    )


def main():
    args = parse_args()
    if not args.command:
        print("Usage: auto_progress.py --tool <name> [--interval N] [-- <command>]", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_with_progress(args))


if __name__ == "__main__":
    main()
