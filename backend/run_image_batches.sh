#!/bin/sh
# Image production daemon: works the pending queue in 250-image chunks with a
# gallery refresh after each. Runs FOREVER (compose service, restart: always):
#   - queue empty        -> idle 30 min, re-check (picks up recreations/rejects)
#   - chunk made no dent -> cool off 1 h (e.g. sustained quota outage), retry
# Logs to stdout -> `docker logs deploy-imageworker-1` (survives restarts).
cd /app || exit 1

count_pending() {
  python -c "from app.core.db import get_client; print(get_client().table('image_assets').select('*',count='exact',head=True).eq('status',0).execute().count)"
}

PREV=-1
while :; do
  PENDING=$(count_pending)
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') pending: $PENDING ==="
  if [ "$PENDING" -le 0 ]; then
    echo "=== queue empty — idling 30 min (recreations/rejects rejoin automatically) ==="
    PREV=-1
    sleep 1800
    continue
  fi
  if [ "$PENDING" = "$PREV" ]; then
    echo "=== no progress in last chunk (stuck at $PENDING) — cooling off 1 h ==="
    PREV=-1
    sleep 3600
    continue
  fi
  PREV=$PENDING
  python generate_images.py --limit 250
  python make_gallery.py
done
