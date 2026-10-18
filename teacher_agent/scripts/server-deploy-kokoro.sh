#!/usr/bin/env bash
# Install a CPU-only Kokoro sidecar, then switch teacher narration after a real
# synthesis succeeds. Configuration and the previous container remain recoverable.
set -Eeuo pipefail
IMAGE="${1:?usage: server-deploy-kokoro.sh IMAGE TAG}"
TAG="${2:?usage: server-deploy-kokoro.sh IMAGE TAG}"
[[ "$IMAGE" =~ ^[a-zA-Z0-9./_-]+$ && "$TAG" =~ ^[a-zA-Z0-9._-]+$ ]] || exit 2
NEW="$IMAGE:$TAG"
NAME=agentic-kokoro
TEACHER=agentic-teacher-prod
ROOT=/opt/agentic-class-pilot/teacher_agent/.runtime/kokoro
ENV_FILE="$HOME/teacher-prod.env"
SNAP="$ROOT/releases/${TAG}-$(date -u +%Y%m%dT%H%M%SZ)"
PREVIOUS="${NAME}-previous-$(date -u +%Y%m%dT%H%M%SZ)"
OLD_EXISTS=0
NEW_STARTED=0
ENV_CHANGED=0

recreate_teacher() {
  local current_image
  current_image="$(cat "$SNAP/teacher-image.txt")"
  docker stop "$TEACHER" >/dev/null 2>&1 || true
  docker rm "$TEACHER" >/dev/null 2>&1 || true
  docker run -d --name "$TEACHER" --network host --restart unless-stopped \
    --env-file "$ENV_FILE" \
    -v /opt/agentic-class-pilot/teacher_agent/server-providers.yml:/app/server-providers.yml:ro \
    -v /home/ubuntu/teacher-agent-data:/app/data \
    "$current_image" >/dev/null
}

wait_url() {
  local url="$1" count code
  for count in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$url" || true)"
    [ "$code" = 200 ] && return 0
    sleep 2
  done
  return 1
}

rollback() {
  trap - ERR
  echo 'Kokoro deployment failed; restoring the previous configuration.'
  if [ "$ENV_CHANGED" = 1 ]; then
    cp -p "$SNAP/teacher-prod.env" "$ENV_FILE"
    recreate_teacher || true
  fi
  if [ "$NEW_STARTED" = 1 ]; then
    docker stop "$NAME" >/dev/null 2>&1 || true
    docker rm "$NAME" >/dev/null 2>&1 || true
  fi
  if [ "$OLD_EXISTS" = 1 ] && docker container inspect "$PREVIOUS" >/dev/null 2>&1; then
    docker rename "$PREVIOUS" "$NAME"
    docker start "$NAME" >/dev/null
  elif [ "$OLD_EXISTS" = 1 ] && [ "$NEW_STARTED" = 0 ]; then
    docker start "$NAME" >/dev/null 2>&1 || true
  fi
  echo "Rollback files: $SNAP"
  exit 1
}

test -f "$ENV_FILE"
docker inspect "$TEACHER" >/dev/null
# Pulling is done before touching either running service or its configuration.
docker pull "$NEW"
if ! mkdir -p "$ROOT" 2>/dev/null; then
  sudo -n install -d -m 0755 -o "$(id -u)" -g "$(id -g)" "$ROOT"
fi
mkdir -p "$ROOT/runtime" "$SNAP"
chmod 700 "$SNAP"
cp -p "$ENV_FILE" "$SNAP/teacher-prod.env"
chmod 600 "$SNAP/teacher-prod.env"
docker inspect "$TEACHER" --format '{{.Config.Image}}' > "$SNAP/teacher-image.txt"
if docker container inspect "$NAME" >/dev/null 2>&1; then
  OLD_EXISTS=1
  docker inspect "$NAME" --format '{{.Config.Image}}' > "$SNAP/tts-image.txt"
fi
trap rollback ERR
if [ "$OLD_EXISTS" = 1 ]; then
  docker stop "$NAME" >/dev/null
  docker rename "$NAME" "$PREVIOUS"
fi
NEW_STARTED=1
docker run -d --name "$NAME" --restart unless-stopped \
  --user "$(id -u):$(id -g)" \
  --cpus=1 --memory=1024m --memory-swap=1024m --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p 127.0.0.1:13305:13305 \
  -v "$ROOT/runtime:/runtime" \
  "$NEW" >/dev/null
wait_url http://127.0.0.1:13305/health

# Measure a complete WAV, not just process liveness. No cloud API is used.
python3 - "$SNAP" <<'PY'
import io, json, pathlib, subprocess, sys, time, urllib.request, wave
root = pathlib.Path(sys.argv[1])
started = time.perf_counter()
text = subprocess.check_output(['docker','exec','agentic-kokoro','cat','/opt/kokoro/narration-smoke.txt'], text=True).strip()
payload = json.dumps({"model":"kokoro-v1","input":text,"response_format":"wav"}, ensure_ascii=False).encode()
request = urllib.request.Request('http://127.0.0.1:13305/v1/audio/speech', data=payload, headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request, timeout=120) as response:
    audio = response.read()
    assert response.headers.get('X-Voice') == 'zf_xiaoyi'
with wave.open(io.BytesIO(audio)) as wav:
    duration = wav.getnframes() / wav.getframerate()
    assert 30 < duration < 120
    assert wav.getframerate() == 24000
(root / 'xiaoyi-smoke.wav').write_bytes(audio)
report = {'voice':'zf_xiaoyi','audioSeconds':round(duration,3),'generationSeconds':round(time.perf_counter()-started,3)}
assert subprocess.check_output(['docker','inspect','agentic-kokoro','--format','{{.RestartCount}}'], text=True).strip() == '0'
(root / 'smoke.json').write_text(json.dumps(report))
print(json.dumps(report))
PY

# Environment values take precedence over server-providers.yml. Existing API
# keys and all non-TTS configuration are preserved, and remain only on the host.
ENV_CHANGED=1
python3 - "$ENV_FILE" <<'PY'
import os, pathlib, re, sys
path = pathlib.Path(sys.argv[1])
values = {
 'TTS_LEMONADE_BASE_URL':'http://127.0.0.1:13305/v1',
 'TTS_LEMONADE_MODELS':'kokoro-v1', 'TTS_LEMONADE_VOICE':'zf_xiaoyi',
 'TTS_QWEN_ENABLED':'false', 'PARALLEL_TTS_CONCURRENCY':'1', 'COURSEWARE_JOB_CONCURRENCY':'1',
}
text = path.read_text()
for key, value in values.items():
    text = re.sub(r'(?m)^'+re.escape(key)+r'=[^\r\n]*(?:\r?\n|$)', '', text)
text = text.rstrip() + '\n' + '\n'.join(f'{key}={value}' for key,value in values.items()) + '\n'
temporary = path.with_suffix('.kokoro-new')
temporary.write_text(text)
os.chmod(temporary, 0o600)
temporary.replace(path)
PY
# Recreating (rather than restarting) is required for Docker to reload env-file.
recreate_teacher
wait_url http://127.0.0.1:3200/api/health

# Verify provider metadata without exposing keys or generated course material.
docker exec -i "$TEACHER" node - <<'JS'
(async () => {
  if (process.env.TTS_LEMONADE_VOICE !== 'zf_xiaoyi' || process.env.TTS_QWEN_ENABLED !== 'false')
    throw new Error('Teacher did not reload its local TTS configuration');
  const response = await fetch('http://127.0.0.1:3200/api/server-providers');
  if (response.status === 401 || response.status === 403 ||
      (response.ok && !response.headers.get('content-type')?.includes('application/json'))) {
    console.log('Provider endpoint requires login; configuration will be checked in the authenticated browser.');
    return;
  }
  const data = await response.json();
  if (!response.ok || !data.tts?.['lemonade-tts'] || data.tts['lemonade-tts'].disabled || !data.tts['qwen-tts']?.disabled)
    throw new Error('Unexpected managed TTS metadata');
  console.log(JSON.stringify({kokoroConfigured:true,qwenTemporarilyDisabled:true}));
})().catch(() => process.exit(1));
JS
printf '%s\n' "$PREVIOUS" > "$SNAP/previous-container.txt"
printf '%s\n' "$NEW" > "$SNAP/new-tts-image.txt"
trap - ERR
echo "KOKORO DEPLOY OK: $NEW"
echo "Configuration backup and smoke test: $SNAP"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' "$NAME" "$TEACHER" || true
