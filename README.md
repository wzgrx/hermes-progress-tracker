# Hermes Progress Tracker

Auto-progress monitoring for hermes-feishu-streaming-card.

Wraps any long-running command, detects percentage progress from stdout,
and pushes real-time updates to Feishu streaming cards.

## Usage

```bash
# Download — auto-detects wget/curl progress
auto_progress.py --tool download -- wget -c <url> -O file

# Compile — auto-detects make/cmake [X%]
auto_progress.py --tool compile --interval 5 -- make -j16

# Manual push
send_progress.py download 45 "45% downloaded" 300
```

## How it works

1. `auto_progress.py` wraps your command as a subprocess
2. Scans stdout for `45%`, `[ 55%]`, `### 45.0%` etc.
3. POSTs progress to sidecar at `/progress` every 5s
4. sidecar updates the Feishu card instantly:
   - **Header**: blue bar + `████░░ 45% ETA 300s`
   - **Tool summary**: `- download: ██████░░ 45%`

## Requirements

- [hermes-feishu-streaming-card](https://github.com/baileyh8/hermes-feishu-streaming-card) v3.4.2+
- Sidecar running on port 18900 (default)

## Install

```bash
pip install -r requirements.txt  # or just copy scripts/ to ~/.hermes/scripts/
chmod +x scripts/*.py
```
