#!/usr/bin/env bash
# Auto Progress Wrapper — transparently wraps long-running commands
# Usage: hermes-progress <command>
#        hermes-progress wget -c https://example.com/file
#        hermes-progress make -j16
#        hermes-progress pip install numpy

set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
AUTO_PROGRESS="$SCRIPT_DIR/auto_progress.py"

# Detect tool name from command
detect_tool() {
    local cmd="$1"
    local base
    base="$(basename "$cmd" 2>/dev/null || echo "$cmd")"
    case "$base" in
        wget)      echo "download" ;;
        curl)      echo "download" ;;
        make)      echo "compile" ;;
        cmake)     echo "configure" ;;
        ninja)     echo "compile" ;;
        pip|pip3)  echo "install" ;;
        git)       echo "git" ;;
        conda)     echo "env" ;;
        apt|apt-get|aptitude) echo "install" ;;
        dd)        echo "dd" ;;
        rsync)     echo "sync" ;;
        ffmpeg)    echo "transcode" ;;
        npm|bun|yarn|pnpm) echo "package" ;;
        cargo)     echo "build" ;;
        python3)   echo "script" ;;
        *)         echo "command" ;;
    esac
}

if [ $# -eq 0 ]; then
    echo "Usage: hermes-progress <command> [args...]"
    exit 1
fi

TOOL=$(detect_tool "$1")
exec python3 "$AUTO_PROGRESS" --tool "$TOOL" -- "$@"
