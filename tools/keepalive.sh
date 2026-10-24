#!/usr/bin/env bash
# Keeps the live bot (and pilot daemon) running without any agent supervision.
# Usage: nohup setsid bash tools/keepalive.sh >> client/logs/keepalive.log 2>&1 &
cd "$(dirname "$0")/.." || exit 1
while true; do
  if ! pgrep -f "client/bot.py --no-update" >/dev/null; then
    echo "$(date +%T) bot not running; restarting"
    ENGINE_CMD="$HOME/.hexbot/live/bp --threads 8" nohup setsid client/.venv/bin/python -u client/bot.py --no-update --pilot client/pilot >> client/logs/live-console.log 2>&1 &
  fi
  if ! pgrep -f "tools/pilot_daemon.py" >/dev/null; then
    echo "$(date +%T) pilot daemon not running; restarting"
    nohup setsid python3 -u tools/pilot_daemon.py --dir client/pilot >> client/pilot/pilot_daemon.log 2>&1 &
  fi
  sleep 30
done
