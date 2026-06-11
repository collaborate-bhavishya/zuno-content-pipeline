#!/usr/bin/env bash
# Pull latest code and rebuild/restart the backend. Safe to run repeatedly.
set -euo pipefail
cd ~/zuno-content-pipeline
git pull --ff-only
cd deploy
docker compose up -d --build
docker image prune -f   # clean up old image layers
echo "✅ Backend updated to $(git -C ~/zuno-content-pipeline rev-parse --short HEAD)"
