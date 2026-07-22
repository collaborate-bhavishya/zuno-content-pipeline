#!/bin/sh
# Content generation daemon (compose service, restart: always): runs the
# lesson batch over whatever the theme catalog says is pending.
#   - batch finishes clean -> idle 30 min, re-check (new catalog rows / CSV
#     uploads generate automatically)
#   - batch self-holds (exit 2: quota outage or diagnosed systemic fault)
#     -> cool off 1 h and retry; transient quota windows heal themselves,
#     real faults keep surfacing in the log every hour until a human looks
# Logs to stdout -> docker logs deploy-contentworker-1
cd /app || exit 1
while :; do
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') content pass starting ==="
  python batch_generate.py
  RC=$?
  if [ "$RC" -eq 2 ]; then
    echo "=== batch SELF-HELD (rc=2) — cooling off 1 h before retry ==="
    sleep 3600
  else
    echo "=== pass done (rc=$RC) — idling 30 min ==="
    sleep 1800
  fi
done
