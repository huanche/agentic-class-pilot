#!/usr/bin/env bash
# Deploy the new student service through the existing agentic-student unit.
# The tiny apps/server.py and apps/start.py entry points keep old unit commands
# working while backend/main.py owns the actual classroom implementation.
set -euo pipefail

TARGET_SHA="${1:?usage: server-deploy-student.sh <commit-sha> <frontend-tarball>}"
TARBALL="${2:?usage: server-deploy-student.sh <commit-sha> <frontend-tarball>}"
REPO=/opt/agentic-class-pilot
SERVICE=agentic-student
STUDENT="$REPO/student_agent"
VENV="$STUDENT/.venv"
HEALTH_URL=http://127.0.0.1:8000/api/session/health
FRONTEND_DIR="$STUDENT/frontend/out"

BACKUP_POLICY=/usr/local/lib/agentic-class-pilot/server-backup-policy.py
test -f "$BACKUP_POLICY" || { echo "FATAL: backup policy not installed"; exit 1; }
sudo -n python3 "$BACKUP_POLICY" apply
exec 9>/tmp/agentic-class-pilot-deploy.lock
flock -w 600 9 || { echo "FATAL: another deployment holds the repo"; exit 1; }

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
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "FATAL: server repo has uncommitted tracked changes — deploy aborted"
  exit 1
fi
OLD_SHA=$(git rev-parse HEAD)
test -s "$TARBALL" || { echo "FATAL: frontend tarball missing: $TARBALL"; exit 1; }
UPDATED=false
BACKUP=""
rollback() {
  if [ "$UPDATED" = true ]; then
    rm -rf "$FRONTEND_DIR"
    if [ -n "$BACKUP" ] && [ -d "$BACKUP" ]; then mv "$BACKUP" "$FRONTEND_DIR"; fi
    git reset --hard "$OLD_SHA"
    if [ -f "$STUDENT/requirements.txt" ]; then
      "$VENV/bin/python" -m pip install -r "$STUDENT/requirements.txt" || true
    fi
    sudo -n systemctl restart "$SERVICE" || true
    wait_healthy || echo "WARNING: rollback health check also failed"
  fi
}
trap 'rollback' ERR
git fetch origin
git merge --ff-only "$TARGET_SHA"
UPDATED=true

if [ ! -x "$VENV/bin/python" ]; then python3 -m venv "$VENV"; fi
"$VENV/bin/python" -m pip install -r "$STUDENT/backend/requirements.txt"
BACKUP="$FRONTEND_DIR.bak-$(date +%Y%m%d%H%M%S)"
if [ -d "$FRONTEND_DIR" ]; then mv "$FRONTEND_DIR" "$BACKUP"; fi
mkdir -p "$FRONTEND_DIR"
tar xzf "$TARBALL" -C "$FRONTEND_DIR"
test -s "$STUDENT/frontend/out/index.html"

if ! sudo -n systemctl restart "$SERVICE" || ! wait_healthy; then
  echo "DEPLOY FAILED — restoring $OLD_SHA"
  rollback
  trap - ERR
  exit 1
fi

trap - ERR
echo "DEPLOY OK: $TARGET_SHA"
ls -1dt "$FRONTEND_DIR".bak-* 2>/dev/null | tail -n +3 | xargs -r rm -rf
