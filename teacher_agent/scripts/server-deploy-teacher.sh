#!/usr/bin/env bash
# Swap the production teacher container to a new image tag, with health check
# and automatic rollback. Invoked by CI (.github/workflows/teacher-deploy.yml)
# over SSH; can also be run manually on the server after `docker login`.
# After a successful swap it also prunes old main-* tags, keeping the deployed
# image plus two successful rollback slots so disk usage stays bounded.
#
# Usage: server-deploy-teacher.sh <image> <tag>
#   e.g. server-deploy-teacher.sh zmzm1443/agentic-teacher main-ceb00dd
set -euo pipefail

IMAGE="${1:?usage: server-deploy-teacher.sh <image> <tag>}"
TAG="${2:?usage: server-deploy-teacher.sh <image> <tag>}"
NEW="$IMAGE:$TAG"
CONTAINER=agentic-teacher-prod
HEALTH_URL=http://127.0.0.1:3200/api/health

BACKUP_POLICY=/usr/local/lib/agentic-class-pilot/server-backup-policy.py
test -f "$BACKUP_POLICY" || { echo "FATAL: backup policy not installed"; exit 1; }
sudo -n python3 "$BACKUP_POLICY" apply

run_container() {
  docker run -d --name "$CONTAINER" \
    --network host --restart unless-stopped \
    --env-file ~/teacher-prod.env \
    -v /opt/agentic-class-pilot/teacher_agent/server-providers.yml:/app/server-providers.yml:ro \
    -v /home/ubuntu/teacher-agent-data:/app/data \
    "$1" >/dev/null
}

wait_healthy() {
  local i code
  for i in $(seq 1 20); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)
    if [ "$code" = "200" ]; then return 0; fi
    sleep 3
  done
  return 1
}

PREV="$(docker inspect "$CONTAINER" --format '{{.Config.Image}}' 2>/dev/null || true)"
echo "current: ${PREV:-<none>}  ->  new: $NEW"

echo "[1/3] Pulling $NEW ..."
pulled=0
for attempt in 1 2 3; do
  if docker pull "$NEW"; then pulled=1; break; fi
  echo "pull attempt $attempt failed; retrying in 10s ..."
  sleep 10
done
if [ "$pulled" != 1 ]; then
  echo "FATAL: could not pull $NEW — leaving current container untouched"
  exit 1
fi

echo "[2/3] Swapping container ..."
docker stop "$CONTAINER" >/dev/null 2>&1 || true
docker rm "$CONTAINER" >/dev/null 2>&1 || true
run_container "$NEW"

echo "[3/3] Health check (up to 60s) ..."
if wait_healthy; then
  echo "DEPLOY OK: $NEW"
  HISTORY=/opt/agentic-class-pilot/.runtime/teacher-successful-images
  mkdir -p "$(dirname "$HISTORY")"
  touch "$HISTORY"
  # Only images observed running or passing this deployment's health check
  # enter the rollback history. Keep current plus two successful predecessors.
  { printf '%s\n' "$NEW"; [ -z "$PREV" ] || printf '%s\n' "$PREV"; cat "$HISTORY"; } \
    | awk 'NF && !seen[$0]++' | head -n 3 > "$HISTORY.tmp"
  mv "$HISTORY.tmp" "$HISTORY"
  if [ -n "$PREV" ] && [ "$PREV" != "$NEW" ]; then
    echo "rollback image kept locally: $PREV"
  fi
  # Reclaim layers orphaned by the swap; tagged rollback images are untouched.
  docker image prune -f >/dev/null 2>&1 || true

  # Prune old deploy tags so disk usage stays flat across deploys: keep the
  # image just deployed and two successful rollback slots; delete
  # every other main-* tag (they stay re-pullable from Docker Hub). The
  # running image is skipped explicitly and plain `docker rmi` also refuses
  # in-use images, so this cannot take down the live container. Best-effort:
  # a cleanup failure must never fail a successful deploy.
  KEEP_PREV="${PREV#"$IMAGE":}"
  RUNNING_ID="$(docker inspect "$CONTAINER" --format '{{.Image}}' 2>/dev/null || true)"
  echo "[cleanup] pruning old '$IMAGE:main-*' tags (keeping $TAG${KEEP_PREV:+ and $KEEP_PREV})"
  docker images "$IMAGE" --format '{{.Tag}} {{.ID}}' | grep -E '^main-[0-9a-f]+' \
    | while read -r t id; do
        [ "$t" = "$TAG" ] && continue
        [ -n "$KEEP_PREV" ] && [ "$t" = "$KEEP_PREV" ] && continue
        grep -Fxq "$IMAGE:$t" "$HISTORY" && continue
        [[ "$RUNNING_ID" == sha256:"$id"* ]] && continue
        echo "[cleanup] docker rmi $IMAGE:$t"
        docker rmi "$IMAGE:$t" >/dev/null 2>&1 || true
      done || true
  exit 0
fi

echo "HEALTH CHECK FAILED for $NEW"
if [ -z "$PREV" ]; then
  echo "FATAL: no previous image to roll back to; container left stopped"
  exit 1
fi
echo "Rolling back to $PREV ..."
docker stop "$CONTAINER" >/dev/null 2>&1 || true
docker rm "$CONTAINER" >/dev/null 2>&1 || true
run_container "$PREV"
if wait_healthy; then
  echo "ROLLBACK OK: $PREV is live again"
else
  echo "FATAL: rollback container also failed health check — manual intervention needed"
fi
exit 1
