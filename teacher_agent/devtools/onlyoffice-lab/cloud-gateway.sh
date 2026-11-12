#!/usr/bin/env bash
# Validates the reversible delta, waits for idle jobs, and restarts this Caddy version.
set -Eeuo pipefail
umask 077
BASE=/opt/agentic-onlyoffice-lab
STATE=/var/lib/agentic-onlyoffice-lab
LIVE=/etc/agentic-class-pilot/Caddyfile.preview
MODE=${1:-}
[[ $EUID == 0 && ( "$MODE" == enable || "$MODE" == disable ) ]] || exit 64
exec 9>/run/lock/agentic-teacher-deploy.lock
flock -n 9 || { echo 'Another deployment or backup owns the maintenance lock'; exit 1; }
[[ $(docker inspect -f '{{.State.Running}}' agentic-teacher-prod) == true ]] || exit 1
LAB_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "agentic-onlyoffice-lab").IPAddress}}' agentic-onlyoffice-lab)
DOCS_IP=$(docker inspect -f '{{(index .NetworkSettings.Networks "agentic-onlyoffice-lab").IPAddress}}' agentic-onlyoffice-docs)
export LAB_UPSTREAM="$LAB_IP:3212" DOCS_UPSTREAM="$DOCS_IP:80"
if [[ $MODE == enable ]]; then
  curl --noproxy '*' -fsS --max-time 5 "http://$LAB_UPSTREAM/onlyoffice-test/health" >/dev/null
  [[ $(curl --noproxy '*' -fsS --max-time 5 "http://$DOCS_UPSTREAM/healthcheck") == true ]] || exit 1
fi
cp -p "$LIVE" "$STATE/Caddyfile.before-last-change"
python3 "$BASE/app/gateway.py" "$MODE" "$LIVE" "$STATE/Caddyfile.candidate"
docker run --rm --network none \
  -v "$STATE/Caddyfile.candidate:/etc/caddy/Caddyfile:ro" \
  -v /etc/agentic-class-pilot/tls:/tls:ro \
  caddy:2.10-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  > "$STATE/gateway-validation.log" 2>&1
[[ $(docker inspect -f '{{json .Config.Cmd}}' agentic-caddy-mainland) == *'"run"'* ]] || exit 1
reload() {
  # The deployed Caddy 2.10 image does not implement SIGUSR1 reload and has admin off.
  # Require the explicit restart mode, with an idle-job check, for this experiment.
  [[ ${LAB_GATEWAY_RELOAD_MODE:-} == restart ]] || {
    echo 'This Caddy version requires LAB_GATEWAY_RELOAD_MODE=restart'; return 1;
  }
  timeout 15s bash /usr/local/libexec/agentic-teacher-wait-idle.sh
  docker restart -t 10 agentic-caddy-mainland >/dev/null
}
recover() {
  local rc=$?
  if (( rc != 0 )); then
    cat "$STATE/Caddyfile.before-last-change" > "$LIVE"
    reload || true
    echo 'LAB_GATEWAY_CHANGE_REVERTED'
  fi
  exit "$rc"
}
trap recover EXIT
# Keep the inode: the live Caddy container bind-mounts this individual file.
cat "$STATE/Caddyfile.candidate" > "$LIVE"
reload
for _ in $(seq 1 20); do
  CODE=$(curl --noproxy '*' --resolve agenticclasspilot.com:443:10.1.0.4 \
    -sS --max-time 5 -o /dev/null -w '%{http_code}' https://agenticclasspilot.com/teacher/api/health || true)
  [[ $CODE == 200 ]] && break
  sleep 1
done
[[ $CODE == 200 ]]
if [[ $MODE == enable ]]; then
  curl --noproxy '*' --resolve agenticclasspilot.com:443:10.1.0.4 \
    -fsS --max-time 10 https://agenticclasspilot.com/onlyoffice-test/health \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["ok"] is True and d["pages"]==5 and d["mode"]=="read-only-lab"'
fi
trap - EXIT
echo "LAB_GATEWAY_${MODE^^}_OK; production health HTTP 200"
