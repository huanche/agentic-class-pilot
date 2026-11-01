#!/usr/bin/env bash
# Roll back this experiment only. Keeps the sample, logs and images for inspection.
set -Eeuo pipefail
[[ $EUID == 0 ]] || exit 1
LAB_GATEWAY_RELOAD_MODE=restart bash /opt/agentic-onlyoffice-lab/app/cloud-gateway.sh disable
for name in agentic-onlyoffice-lab agentic-onlyoffice-docs; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    [[ $(docker inspect -f '{{index .Config.Labels "org.agentedu.lab"}}' "$name") == onlyoffice-20261101 ]] || exit 1
    docker stop -t 30 "$name" >/dev/null
  fi
done
echo 'ONLYOFFICE_LAB_STOPPED; production teacher unchanged'
