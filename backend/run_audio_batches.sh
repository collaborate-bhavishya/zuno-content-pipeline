#!/bin/sh
# Audio production daemon (compose service, restart: always): works the whole
# pending audio_assets queue, then idles 30 min and re-checks — so audio for
# future lessons appears automatically. Logs to stdout (docker logs).
cd /app || exit 1
while :; do
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') audio pass starting ==="
  python generate_audio.py
  echo "=== $(date -u '+%Y-%m-%d %H:%M:%S') pass done — idling 30 min ==="
  sleep 1800
done
