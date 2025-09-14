#!/usr/bin/env bash
set -euo pipefail

# Usage: bash scripts/update.sh [branch]
# Default branch: main

BRANCH="${1:-main}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

echo "[info] Backing up SQLite DB if present..."
mkdir -p data
if [ -f data/subscriptions.db ]; then
  cp -a "data/subscriptions.db" "data/subscriptions.db.bak-${TIMESTAMP}"
  echo "[ok] Backup: data/subscriptions.db.bak-${TIMESTAMP}"
else
  echo "[skip] No data/subscriptions.db found"
fi

echo "[info] Fetching latest code..."
git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

echo "[info] Rebuilding and restarting via Docker Compose..."
docker compose up -d --build

echo "[info] Pruning dangling images..."
docker image prune -f >/dev/null 2>&1 || true

echo "[done] Update complete."

