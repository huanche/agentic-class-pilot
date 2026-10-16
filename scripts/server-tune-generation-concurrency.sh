#!/usr/bin/env bash
# Tune the existing bounded pipeline without changing the model, voice or deck.
# Usage: script check|apply 0|2 <numeric-operation-id>
set -euo pipefail
mode="${1:-check}"
requested="${2:-2}"
operation_id="${3:?numeric operation id required}"
[[ "$mode" = check || "$mode" = apply ]]
[[ "$requested" = 0 || "$requested" = 2 ]]
[[ "$operation_id" =~ ^[0-9]+$ ]]
container=agentic-teacher-prod
env_file="${GENERATION_TUNING_ENV_FILE:-$HOME/teacher-prod.env}"
backup_file="$env_file.pre-parallel-$operation_id"
deploy_script="${GENERATION_TUNING_DEPLOY_SCRIPT:-/tmp/server-deploy-teacher.sh}"
[[ -f "$env_file" ]]
image="$(docker inspect "$container" --format '{{.Config.Image}}')"
[[ "$image" = zmzm1443/agentic-teacher:* ]]
docker exec "$container" node -e 'console.log(JSON.stringify({check:"generation-concurrency",parallel:process.env.PARALLEL_SCENE_CONCURRENCY||"unset",model:process.env.DEFAULT_MODEL}))'
if [[ "$mode" = check ]]; then exit 0; fi
[[ -f "$deploy_script" ]]
[[ ! -e "$backup_file" ]]
umask 077
cp -- "$env_file" "$backup_file"
chmod 600 "$backup_file"
python3 - "$env_file" "$requested" <<'PY'
import os,pathlib,stat,sys,tempfile
target=pathlib.Path(sys.argv[1]);value=sys.argv[2]
original=target.stat()
lines=target.read_text().splitlines()
lines=[line for line in lines if not line.startswith('PARALLEL_SCENE_CONCURRENCY=')]
lines.append('PARALLEL_SCENE_CONCURRENCY='+value)
descriptor,temporary=tempfile.mkstemp(prefix=target.name+'.',dir=target.parent)
try:
    with os.fdopen(descriptor,'w') as output: output.write('\n'.join(lines)+'\n')
    os.chmod(temporary,stat.S_IMODE(original.st_mode));os.replace(temporary,target)
finally:
    if os.path.exists(temporary): os.unlink(temporary)
PY
repository="${image%:*}"
tag="${image##*:}"
if bash "$deploy_script" "$repository" "$tag"; then
  actual="$(docker exec "$container" printenv PARALLEL_SCENE_CONCURRENCY)"
  if [[ "$actual" = "$requested" ]]; then
    echo "CONCURRENCY OK: $actual; private env backup retained: $backup_file"
    exit 0
  fi
fi
echo 'Configuration verification failed; restoring the previous environment.'
cp -- "$backup_file" "$env_file"
chmod 600 "$env_file"
bash "$deploy_script" "$repository" "$tag"
exit 1
