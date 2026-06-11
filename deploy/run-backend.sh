#!/usr/bin/env bash
# Build and (re)start the backend container. Run on the EC2 instance.
# Reads secrets from backend/prod.env (you create it; never committed).
# Optionally mounts a Google service-account JSON if backend/gcp-key.json exists.
set -euo pipefail

cd "$(dirname "$0")/../backend"

if [ ! -f prod.env ]; then
  echo "ERROR: backend/prod.env not found. Create it first (see deploy/README.md)." >&2
  exit 1
fi

echo "==> Building image"
docker build -t zuno-backend .

echo "==> Restarting container"
docker rm -f zuno-backend 2>/dev/null || true

CREDS_ARGS=()
if [ -f gcp-key.json ]; then
  CREDS_ARGS=(-v "$PWD/gcp-key.json:/app/gcp-key.json:ro"
              -e GOOGLE_APPLICATION_CREDENTIALS=/app/gcp-key.json)
  echo "==> Mounting Google service-account key"
fi

docker run -d --name zuno-backend --restart unless-stopped \
  -p 8000:8000 \
  --env-file prod.env \
  "${CREDS_ARGS[@]}" \
  zuno-backend

echo
echo "✅ Backend running on port 8000."
echo "   Logs:   docker logs -f zuno-backend"
echo "   Health: curl http://localhost:8000/api/health"
