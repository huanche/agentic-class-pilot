#!/usr/bin/env bash
# Deploy the student agent on the production server: fast-forward the repo to
# the requested commit, rebuild the static frontend bundle, swap the served
# copy, and restart the systemd service — with health check and automatic
# rollback. Invoked by CI (.github/workflows/student-deploy.yml) over SSH;
# can also be run manually on the server:
#
#   bash student_agent/scripts/server-deploy-student.sh <commit-sha>
#
# One-time server prerequisite (CI ssh sessions are non-interactive):
#   ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart agentic-student
set -euo pipefail

TARGET_SHA="${1:?usage: server-deploy-student.sh <commit-sha>}"
REPO=/opt/agentic-class-pilot
SERVICE=agentic-student
FRONTEND="$REPO/student_agent/frontend"
STATIC_APP="$REPO/student_agent/apps/static/app"
HEALTH_URL=http://127.0.0.1:8000/api/session/health

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
[ "$OLD_SHA" = "$TARGET_SHA" ] && echo "already at target; redeploying bundle only"

echo "[1/4] Fetching and fast-forwarding ..."
git fetch origin
git merge --ff-only "$TARGET_SHA"

echo "[2/4] Building frontend (static export + fingerprint) ..."
( cd "$FRONTEND" && npm run build )
test -s "$FRONTEND/out/.build-fingerprint" || {
  echo "FATAL: build produced no .build-fingerprint"; exit 1; }
FINGERPRINT=$(cat "$FRONTEND/out/.build-fingerprint")

echo "[3/4] Swapping static bundle (previous kept for rollback) ..."
BACKUP="$STATIC_APP.bak-$(date +%Y%m%d%H%M%S)"
if [ -d "$STATIC_APP" ]; then mv "$STATIC_APP" "$BACKUP"; fi
# rsync -a carries dotfiles too — the runtime fingerprint guard depends on it.
rsync -a "$FRONTEND/out/" "$STATIC_APP/"

echo "[4/4] Restarting $SERVICE + health check (up to 60s) ..."
if ! restart_service || ! wait_healthy; then
  echo "DEPLOY FAILED — rolling back to $OLD_SHA"
  rm -rf "$STATIC_APP"
  [ -d "$BACKUP" ] && mv "$BACKUP" "$STATIC_APP"
  git reset --hard "$OLD_SHA"
  restart_service || true
  wait_healthy || echo "WARNING: rollback health check also failing — inspect manually"
  exit 1
fi

echo "DEPLOY OK: $TARGET_SHA (fingerprint ${FINGERPRINT:0:12}…)"
# Keep the two most recent backups for manual recovery; prune the rest.
ls -1dt "$STATIC_APP".bak-* 2>/dev/null | tail -n +3 | xargs -r rm -rf
if [ -n "$(ls -1d "$STATIC_APP".bak-* 2>/dev/null)" ]; then
  echo "rollback bundle(s) kept: $(ls -1dt "$STATIC_APP".bak-* | head -2 | tr '\n' ' ')"
fi
