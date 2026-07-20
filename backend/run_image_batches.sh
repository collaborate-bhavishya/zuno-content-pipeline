#!/bin/sh
# Full image production: 250-image chunks with a gallery refresh after each,
# until the queue is empty. Safe to stop/restart — the status flags resume.
#
#   docker exec -d -w /app <container> sh run_image_batches.sh
#   (logs to /app/storage/images_full.log via the launch redirection)
cd /app || exit 1

PREV=-1
while :; do
  PENDING=$(python -c "from app.core.db import get_client; print(get_client().table('image_assets').select('*',count='exact',head=True).eq('status',0).execute().count)")
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') pending: $PENDING ==="
  if [ "$PENDING" -le 0 ]; then
    echo "=== QUEUE EMPTY — FULL IMAGE RUN COMPLETE ==="
    break
  fi
  if [ "$PENDING" = "$PREV" ]; then
    echo "=== NO PROGRESS in last chunk (stuck at $PENDING) — stopping so a human can look ==="
    break
  fi
  PREV=$PENDING
  python generate_images.py --limit 250
  python make_gallery.py
done
