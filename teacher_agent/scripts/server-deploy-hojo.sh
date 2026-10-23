#!/usr/bin/env bash
# Optional loopback CPU TTS; Kokoro and its default selection are preserved.
set -Eeuo pipefail
IMAGE="${1:?usage: server-deploy-hojo.sh IMAGE TAG}"
TAG="${2:?usage: server-deploy-hojo.sh IMAGE TAG}"
[[ "$IMAGE" =~ ^[a-zA-Z0-9./_-]+$ && "$TAG" =~ ^[a-zA-Z0-9._-]+$ ]] || exit 2
NEW="$IMAGE:$TAG"
NAME=agentic-hojo
ROOT=/opt/agentic-class-pilot/teacher_agent/.runtime/hojo
ENV_FILE="$HOME/teacher-prod.env"
SNAP="$ROOT/releases/${TAG}-$(date -u +%Y%m%dT%H%M%SZ)"
PREVIOUS="${NAME}-previous-$(date -u +%Y%m%dT%H%M%SZ)"
OLD_EXISTS=0
NEW_STARTED=0
ENV_CHANGED=0
sudo -n python3 /usr/local/lib/agentic-class-pilot/server-backup-policy.py preflight
docker pull "$NEW"
if ! mkdir -p "$ROOT" 2>/dev/null; then
  sudo -n install -d -m 0755 -o "$(id -u)" -g "$(id -g)" "$ROOT"
fi
mkdir -p "$ROOT/runtime" "$SNAP"
chmod 700 "$SNAP"
cp -p "$ENV_FILE" "$SNAP/teacher-prod.env"
chmod 600 "$SNAP/teacher-prod.env"
docker inspect agentic-teacher-prod --format '{{.Config.Image}}' > "$SNAP/teacher-image.txt"

rollback() {
  trap - ERR
  if [ "$ENV_CHANGED" = 1 ]; then
    cp -p "$SNAP/teacher-prod.env" "$ENV_FILE"
    bash /tmp/server-deploy-teacher.sh "$(cat "$SNAP/teacher-image.txt" | cut -d: -f1)" "$(cat "$SNAP/teacher-image.txt" | cut -d: -f2)" || true
  fi
  if [ "$NEW_STARTED" = 1 ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; fi
  if [ "$OLD_EXISTS" = 1 ]; then
    docker rename "$PREVIOUS" "$NAME"
    docker start "$NAME" >/dev/null
  fi
  echo "ERROR: Hojo deployment rolled back; configuration backup: $SNAP"
  exit 1
}
trap rollback ERR
if docker container inspect "$NAME" >/dev/null 2>&1; then
  docker stop "$NAME" >/dev/null
  docker rename "$NAME" "$PREVIOUS"
  OLD_EXISTS=1
fi
docker run -d --name "$NAME" --network host --restart unless-stopped \
  --user "$(id -u):$(id -g)" --cpus=0.75 --memory=1536m --memory-swap=2560m --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,nosuid,size=256m --log-opt max-size=10m --log-opt max-file=3 \
  -v "$ROOT/runtime:/runtime" "$NEW" >/dev/null
NEW_STARTED=1
ready=0
for attempt in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:13306/health >/dev/null; then ready=1; break; fi
  sleep 2
done
[ "$ready" = 1 ]
docker exec -i "$NAME" python - < /tmp/hojo-smoke.py | tee "$SNAP/smoke.txt"
[ "$(docker inspect "$NAME" --format '{{.RestartCount}}')" = 0 ]
[ "$(docker inspect "$NAME" --format '{{.State.OOMKilled}}')" = false ]

# Add only this optional provider. Do not pin models (the teacher chooses 40M/80M).
ENV_CHANGED=1
python3 - "$ENV_FILE" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
lines = path.read_text().splitlines()
values = {'TTS_HOJO_ENABLED': 'true', 'TTS_HOJO_BASE_URL': 'http://127.0.0.1:13306/v1'}
lines = [line for line in lines if line.split('=',1)[0] not in values and not line.startswith('TTS_HOJO_MODELS=')]
lines.extend(k+'='+v for k,v in values.items())
temp = path.with_suffix('.hojo.tmp')
temp.write_text('\n'.join(lines)+'\n')
temp.chmod(0o600)
os.replace(temp, path)
PY
current="$(cat "$SNAP/teacher-image.txt")"
bash /tmp/server-deploy-teacher.sh "${current%:*}" "${current##*:}"
python3 - "$ENV_FILE" "$SNAP/teacher-prod.env" <<'PY'
import pathlib, sys
def config(p): return dict(line.split('=',1) for line in pathlib.Path(p).read_text().splitlines() if line and not line.startswith('#') and '=' in line)
after,before = map(config,sys.argv[1:])
assert {k:v for k,v in after.items() if not k.startswith('TTS_HOJO_')} == {k:v for k,v in before.items() if not k.startswith('TTS_HOJO_')}
assert after.get('TTS_LEMONADE_ENABLED') == 'true'
assert after.get('TTS_LEMONADE_MODELS') == 'kokoro-v1'
print('VERIFY_DEFAULT_KOKORO_PRESERVED')
PY
curl -fsS --max-time 5 http://127.0.0.1:13305/health >/dev/null
echo "DEPLOY OK: optional Hojo $NEW; Kokoro retained; backup $SNAP"
