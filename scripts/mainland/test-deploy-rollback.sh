#!/bin/bash
# Exercise the installed deploy state machine against disposable HTTP containers.
# No production credentials, application data or production deployment switch are used.
set -Eeuo pipefail
umask 077
BASE=/srv/agentic-migration-audit/20261031/deploy-test
NAME=agentic-teacher-migration-test
UNIT=agentic-teacher-migration-test-forward.service
IMAGE=ccr.ccs.tencentyun.com/agentedu-mainland/agentic-teacher
[[ $EUID == 0 && $(hostname) == VM-0-4-ubuntu ]]
[[ ! -e /etc/agentic-class-pilot/teacher-deploy-enabled ]]
mkdir -p "$BASE/data" "$BASE/prepared"
printf 'DEEPSEEK_BASE_URL=https://api.deepseek.com\n' > "$BASE/teacher.env"
printf '{}\n' > "$BASE/providers.yml"
touch "$BASE/enabled"
printf '#!/bin/bash\nexit 0\n' > "$BASE/wait-idle"
chmod 700 "$BASE/wait-idle"
chmod 600 "$BASE/teacher.env" "$BASE/enabled"
cleanup() {
  rc=$?
  trap - EXIT
  set +e
  systemctl stop "$UNIT"
  while read -r container; do
    [[ $container == "$NAME" || $container == "$NAME"-rollback-* || $container == "$NAME"-seed-* ]] && docker rm -f "$container" >/dev/null
  done < <(docker ps -a --format '{{.Names}}' --filter "name=$NAME")
  rm -f /etc/systemd/system/agentic-teacher-migration-test-forward.service
  systemctl daemon-reload
  docker image rm "$IMAGE:main-0000001" "$IMAGE:main-0000002" >/dev/null 2>&1
  exit "$rc"
}
trap cleanup EXIT
for item in '0000001 200' '0000002 500'; do
  read -r tag code <<< "$item"
  docker create --name "$NAME-seed-$tag" --entrypoint node \
    zmzm1443/agentic-teacher:main-df839c6 \
    -e "require('http').createServer((q,s)=>{s.writeHead($code);s.end('test')}).listen(3200,'0.0.0.0')" >/dev/null
  docker commit "$NAME-seed-$tag" "$IMAGE:main-$tag" >/dev/null
  docker rm "$NAME-seed-$tag" >/dev/null
  ID=$(docker image inspect -f '{{.Id}}' "$IMAGE:main-$tag")
  printf '{"image":"%s:main-%s","id":"%s"}\n' "$IMAGE" "$tag" "$ID" > "$BASE/prepared/main-$tag.json"
done
python3 - "$BASE" <<'PY'
from pathlib import Path
import re, sys
b = Path(sys.argv[1])
s = Path('/usr/local/sbin/agentic-teacher-deploy').read_text()
replacements = {
    'NAME=agentic-teacher-prod': 'NAME=agentic-teacher-migration-test',
    'PREPARED=/var/lib/agentic-class-pilot/prepared-images': f'PREPARED={b}/prepared',
    'BACKUP=/usr/local/sbin/agentic-mainland-backup': 'BACKUP=/bin/true',
    'ENVFILE=/etc/agentic-class-pilot/teacher.env': f'ENVFILE={b}/teacher.env',
    'DATA=/home/ubuntu/teacher-agent-data': f'DATA={b}/data',
    'CONFIG=/opt/agentic-class-pilot/teacher_agent/server-providers.yml': f'CONFIG={b}/providers.yml',
    'FORWARD=agentic-teacher-forward.service': 'FORWARD=agentic-teacher-migration-test-forward.service',
    'WAIT=/usr/local/libexec/agentic-teacher-wait-idle.sh': f'WAIT={b}/wait-idle',
    'ENABLE=/etc/agentic-class-pilot/teacher-deploy-enabled': f'ENABLE={b}/enabled',
    '127.0.0.1:3200': '127.0.0.1:13200',
    'for _ in $(seq 1 30)': 'for _ in $(seq 1 3)',
}
for old, new in replacements.items():
    assert old in s, old
    s = s.replace(old, new)
s, count = re.subn(r'verify_new_ai_tls\(\) \{.*?\n\}\n', 'verify_new_ai_tls() { return 0; }\n', s, count=1, flags=re.S)
assert count == 1
(b / 'deploy-under-test').write_text(s)
forward = Path('/usr/local/libexec/agentic-teacher-forward.sh').read_text()
forward = forward.replace('agentic-teacher-prod', 'agentic-teacher-migration-test').replace('LISTEN:3200', 'LISTEN:13200')
(b / 'forward').write_text(forward)
PY
chmod 700 "$BASE/deploy-under-test" "$BASE/forward"
bash -n "$BASE/deploy-under-test"
cat > /etc/systemd/system/agentic-teacher-migration-test-forward.service <<UNIT
[Service]
ExecStart=$BASE/forward
UNIT
systemctl daemon-reload
docker run -d --name "$NAME" --network agentic-migration-internal --restart no \
  --env-file "$BASE/teacher.env" --mount "type=bind,source=$BASE/data,target=/app/data" \
  "$IMAGE:main-0000001" >/dev/null
systemctl start "$UNIT"
sleep 2
"$BASE/deploy-under-test" deploy-local "$IMAGE" main-0000001
ORIGINAL_ID=$(docker inspect -f '{{.Id}}' "$NAME")
set +e
"$BASE/deploy-under-test" deploy-local "$IMAGE" main-0000002
FAILED_RC=$?
set -e
[[ $FAILED_RC != 0 ]]
[[ $(docker inspect -f '{{.Id}}' "$NAME") == "$ORIGINAL_ID" ]]
[[ $(curl --noproxy '*' -s --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:13200/api/health) == 200 ]]
[[ ! -e /etc/agentic-class-pilot/teacher-deploy-enabled ]]
printf 'ISOLATED_DEPLOY_AND_ROLLBACK_VERIFIED original_container=%s\n' "$ORIGINAL_ID"
