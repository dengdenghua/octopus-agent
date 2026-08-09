#!/usr/bin/env bash
# Watchdog for the octopus backend on :8000.
#
# The backend has been killed by external tooling four times (15:45 / 23:36 /
# 02:07...). This loop health-checks :8000 every 30s and restarts the server
# when it is down. Logs to /tmp/octopus-watchdog.log.
#
# Usage:  bash scripts/watchdog_backend.sh   (keep it running in the background)
# For a boot-persistent guard use the launchd agent:
#   launchctl load ~/Library/LaunchAgents/com.octopus.backend.plist
set -u

HEALTH_URL="http://127.0.0.1:8000/"
CHECK_INTERVAL=30
SERVER_CMD="cd /Users/dangbei/Public/octopus/octopus-agent && ./.venv/bin/python -m runtime serve --config config.local.yaml --port 8000"
LOG=/tmp/octopus-watchdog.log

echo "$(date '+%F %T') watchdog started" >> "$LOG"

while true; do
  if ! curl -s -o /dev/null --max-time 5 "$HEALTH_URL"; then
    echo "$(date '+%F %T') backend DOWN — restarting" >> "$LOG"
    stale=$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null)
    if [ -n "$stale" ]; then
      kill "$stale" 2>/dev/null
      sleep 1
    fi
    bash -c "$SERVER_CMD" >> /tmp/octopus-backend.log 2>&1 &
    echo "$(date '+%F %T') backend restarted (pid $!)" >> "$LOG"
  fi
  sleep "$CHECK_INTERVAL"
done
