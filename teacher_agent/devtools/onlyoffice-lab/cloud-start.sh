#!/usr/bin/env bash
# Starts only the isolated, fixed-sample experiment. Does not replace teacher production.
set -Eeuo pipefail
umask 077
BASE=/opt/agentic-onlyoffice-lab
STATE=/var/lib/agentic-onlyoffice-lab
NETWORK=agentic-onlyoffice-lab
DOCS=agentic-onlyoffice-docs
LAB=agentic-onlyoffice-lab
LABEL=onlyoffice-20261101
PIN=sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3

[[ $EUID == 0 ]] || { echo 'Root is required for the isolated container setup'; exit 1; }
[[ -f "$STATE/config.json" && -f "$BASE/data/audio-report.json" ]] || {
  echo 'Verified sample, dedicated credentials and narration must be staged first'; exit 1;
}
[[ $(awk '/MemAvailable/ {print $2}' /proc/meminfo) -ge 5242880 ]] || {
  echo 'At least 5 GiB available RAM is required before starting this lab'; exit 1;
}
[[ $(df --output=avail -B1 "$BASE" | tail -n 1) -ge 10737418240 ]] || {
  echo 'At least 10 GiB free disk space is required'; exit 1;
}
docker container inspect "$DOCS" >/dev/null 2>&1 && { echo 'Docs lab already exists; inspect it before changing it'; exit 1; }
docker container inspect "$LAB" >/dev/null 2>&1 && { echo 'Player lab already exists; inspect it before changing it'; exit 1; }
DOC_IMAGE="docker.m.daocloud.io/onlyoffice/documentserver@$PIN"
docker image inspect "$DOC_IMAGE" >/dev/null
[[ $(docker image inspect -f '{{json .RepoDigests}}' "$DOC_IMAGE") == *"@$PIN"* ]] || exit 1
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create --internal "$NETWORK" >/dev/null
[[ $(docker network inspect -f '{{.Internal}}' "$NETWORK") == true ]] || exit 1
NODE_IMAGE=$(cat "$STATE/teacher-image.before")
docker image inspect "$NODE_IMAGE" >/dev/null
chown 1000:1000 "$STATE/config.json"
install -d -m 700 -o 1000 -g 1000 "$STATE/playback"
find "$BASE/app" -type d -exec chmod 755 {} +
find "$BASE/app" -type f -exec chmod 644 {} +
docker run -d --name "$LAB" --pull never --restart no \
  --label "org.agentedu.lab=$LABEL" --user 1000:1000 \
  --network agentic-migration-internal \
  --cpus 0.5 --memory 256m --pids-limit 128 --read-only --tmpfs /tmp:size=32m \
  --env-file "$STATE/auth.env" -e PORT=3212 \
  -e ONLYOFFICE_LAB_CONFIG=/lab-config.json \
  -v "$BASE/app:/lab:ro" -v "$BASE/data:/lab-data:ro" \
  -v "$STATE/config.json:/lab-config.json:ro" -v "$STATE/playback:/lab-state:rw" \
  --entrypoint node "$NODE_IMAGE" /lab/server.mjs >/dev/null
docker network connect "$NETWORK" "$LAB"
docker run -d --name "$DOCS" --pull never --restart no \
  --label "org.agentedu.lab=$LABEL" --network "$NETWORK" \
  --cpus 2 --memory 4g --memory-swap 5g --pids-limit 1024 \
  --shm-size 256m --env-file "$STATE/onlyoffice.env" "$DOC_IMAGE" >/dev/null
echo 'ISOLATED_LAB_CONTAINERS_STARTED; production container unchanged'
