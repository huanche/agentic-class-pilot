#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && ( ${1:-} == enable || ${1:-} == disable ) ]] || exit 64
python3 - "$1" <<'PY'
import json,sys
from pathlib import Path
p=Path('/var/lib/agentic-onlyoffice-player/config.json')
data=json.loads(p.read_text());data['nativeEnabled']=sys.argv[1]=='enable'
# Preserve inode: this individual file is bind-mounted into the service.
with p.open('w') as f:json.dump(data,f)
print('NATIVE_PLAYER_ENABLED' if data['nativeEnabled'] else 'NATIVE_PLAYER_DISABLED')
PY
