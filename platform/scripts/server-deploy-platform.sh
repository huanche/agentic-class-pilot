#!/usr/bin/env bash
# Deploy the platform (backend + frontend) on the production server: fast-forward
# the repo to the requested commit, sync Python deps, run alembic migrations,
# swap the built frontend bundle (uploaded by CI — the server has no bun), and
# restart the systemd service — with health check and automatic rollback.
#
# Invoked by CI (.github/workflows/platform-deploy.yml) over SSH as:
#   server-deploy-platform.sh <commit-sha> <frontend-tarball>
# The tarball must contain the built frontend files (bun run --filter frontend
# build output, i.e. the CONTENTS of platform/backend/app/frontend).
#
# One-time server prerequisites:
#   - uv at ~/.local/bin/uv (backend dep sync)
#   - sudoers: ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart agentic-platform
#
# Rollback note: frontend bundle, code and deps are rolled back automatically;
# alembic migrations are NOT auto-downgraded (they are additive in practice —
# a rolled-back backend simply ignores newer columns/tables).
set -euo pipefail

TARGET_SHA="${1:?usage: server-deploy-platform.sh <commit-sha> <frontend-tarball>}"
TARBALL="${2:?usage: server-deploy-platform.sh <commit-sha> <frontend-tarball>}"
REPO=/opt/agentic-class-pilot
SERVICE=agentic-platform
PLATFORM="$REPO/platform"
FRONTEND_DIR="$PLATFORM/backend/app/frontend"
HEALTH_URL=http://127.0.0.1:8080/health
export PATH="$HOME/.local/bin:$PATH"

restart_service() { sudo -n systemctl restart "$SERVICE"; }

wait_healthy() {
  local i code
  for i in $(seq 1 20); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)
    if [ "$code" = "200" ]; then return 0; fi
    sleep 3
  done
  return 1
}

cd "$REPO"

# Refuse to run over local modifications — rollback resets --hard and must
# never destroy uncommitted overlay work. Untracked files are fine.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "FATAL: server repo has uncommitted tracked changes — deploy aborted"
  git status --short --untracked-files=no
  exit 1
fi

OLD_SHA=$(git rev-parse HEAD)
echo "current: $OLD_SHA  ->  target: $TARGET_SHA"

test -s "$TARBALL" || { echo "FATAL: frontend tarball missing: $TARBALL"; exit 1; }

echo "[1/5] Fetching and fast-forwarding ..."
git fetch origin
git merge --ff-only "$TARGET_SHA"

echo "[2/5] Syncing backend deps (uv) ..."
( cd "$PLATFORM" && uv sync --frozen --package app )

echo "[3/5] Running alembic migrations ..."
( cd "$PLATFORM/backend" && ../.venv/bin/python -m alembic upgrade head ) || {
  echo "FATAL: migration failed — code rolled back, service untouched"
  git reset --hard "$OLD_SHA"
  exit 1
}

echo "[4/5] Swapping frontend bundle (previous kept for rollback) ..."
BACKUP="$FRONTEND_DIR.bak-$(date +%Y%m%d%H%M%S)"
if [ -d "$FRONTEND_DIR" ]; then mv "$FRONTEND_DIR" "$BACKUP"; fi
mkdir -p "$FRONTEND_DIR"
tar xzf "$TARBALL" -C "$FRONTEND_DIR"

echo "[5/5] Restarting $SERVICE + health check (up to 60s) ..."
if ! restart_service || ! wait_healthy; then
  echo "DEPLOY FAILED — rolling back to $OLD_SHA"
  rm -rf "$FRONTEND_DIR"
  [ -d "$BACKUP" ] && mv "$BACKUP" "$FRONTEND_DIR"
  git reset --hard "$OLD_SHA"
  ( cd "$PLATFORM" && uv sync --frozen --package app ) || true
  restart_service || true
  wait_healthy || echo "WARNING: rollback health check also failing — inspect manually"
  exit 1
fi

echo "DEPLOY OK: $TARGET_SHA"
# Keep the two most recent backups for manual recovery; prune the rest.
ls -1dt "$FRONTEND_DIR".bak-* 2>/dev/null | tail -n +3 | xargs -r rm -rf
echo "note: alembic migrations applied by this deploy are not auto-downgraded"
