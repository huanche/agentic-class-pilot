#!/usr/bin/env python3
"""Conservative mainland maintenance; plan by default, explicit apply required.

Keep configured containers and the newest two rollbacks per service. Only remove
unreferenced stopped containers older than seven days. Never remove volumes.
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

ROOTS = ('/etc/systemd/system', '/etc/agentic-class-pilot',
         '/usr/local/sbin', '/usr/local/lib/agentic-class-pilot')
LEGACY = set('''agentic-teacher-nav-captions-live agentic-teacher-nav-captions-ready
agentic-teacher-nav-captions agentic-teacher-player-a-ready agentic-teacher-player-a
agentic-teacher-unified-ready agentic-teacher-unified-player agentic-teacher-mixed-fidelity
agentic-teacher-autohide-live agentic-teacher-autohide-ready agentic-teacher-player-autohide
agentic-teacher-player-controls agentic-teacher-player-ui agentic-teacher-video-ready
agentic-classroom-video-canary agentic-teacher-video-candidate'''.split())
HISTORICAL = '''migration-20261031-174153 migration-20261103-135119
migration-20261105-190829 migration-20261113-142512 migration-20261113-154234'''.split()


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def health():
    for url in ('http://127.0.0.1:8080/api/v1/utils/health-check/',
                'http://127.0.0.1:8000/api/session/health',
                'http://127.0.0.1:3200/api/health'):
        assert run('curl', '-s', '--max-time', '10', '-o', '/dev/null', '-w', '%{http_code}', url) == '200', url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--retire-legacy', action='store_true', help='One-time audited legacy containers')
    parser.add_argument('--release-historical-backups', action='store_true', help='One-time approved five snapshots')
    args = parser.parse_args()
    assert os.geteuid() == 0 and socket.gethostname() == 'VM-0-4-ubuntu'
    locks = []
    for name in ('/run/lock/agentic-teacher-deploy.lock', '/srv/backup-policy.lock'):
        lock = open(name, 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('SKIP: deployment or backup is active')
            return
        locks.append(lock)
    health()
    texts = []
    for root in ROOTS:
        for p in Path(root).rglob('*'):
            if p.is_file() and p.resolve() != Path(__file__).resolve() and p.stat().st_size < 1000000 and '__pycache__' not in str(p):
                texts.append(p.read_text(errors='replace'))
    config = '\n'.join(texts)
    cs = json.loads(run('docker', 'inspect', *run('docker', 'ps', '-aq').split()))
    def referenced(c):
        tokens = [c['Name'][1:]] + [n['IPAddress'] for n in c['NetworkSettings']['Networks'].values() if n['IPAddress']]
        # Bound tokens: avoid treating .2 as a match for .20.
        return any(re.search(r'(?<![\w.-])' + re.escape(t) + r'(?![\w.-])', config) for t in tokens)
    protected = {c['Id'] for c in cs if referenced(c)}
    # Environment references from containers outside the explicit retirement set.
    for other in cs:
        if other['State']['Running'] and other['Name'][1:] not in LEGACY:
            env = json.dumps(other['Config'].get('Env', [])) + json.dumps(other['HostConfig'].get('ExtraHosts', []))
            for c in cs:
                tokens = [c['Name'][1:]] + [n['IPAddress'] for n in c['NetworkSettings']['Networks'].values() if n['IPAddress']]
                if any(re.search(r'(?<![\w.-])' + re.escape(t) + r'(?![\w.-])', env) for t in tokens):
                    protected.add(c['Id'])
    groups = {}
    for c in cs:
        if '-rollback-' in c['Name']:
            groups.setdefault(c['Name'].split('-rollback-')[0], []).append(c)
    for group in groups.values():
        protected.update(c['Id'] for c in sorted(group, key=lambda c: c['Created'], reverse=True)[:2])
    images = set()
    removed = 0
    for c in cs:
        name = c['Name'][1:]
        if c['Id'] in protected or not name.startswith('agentic-'):
            continue
        legacy = args.retire_legacy and name in LEGACY
        finished = c['State']['FinishedAt']
        old = not c['State']['Running'] and finished.startswith('20') and time.time() - datetime.datetime.fromisoformat(finished[:26] + '+00:00').timestamp() > 7 * 86400
        if not (legacy or old):
            continue
        print('REMOVE_CONTAINER', name, flush=True)
        if args.apply:
            if c['State']['Running']:
                run('docker', 'stop', '-t', '30', name)
                try:
                    health()
                except Exception:
                    run('docker', 'start', name)
                    raise
            run('docker', 'rm', name)  # No force and no volume deletion.
            removed += 1
            images.add(c['Image'])
    for image in sorted(images):
        if image in config or image.split(':')[-1] in config:
            continue
        # Docker refuses images still referenced by any container; never force.
        result = subprocess.run(['docker', 'image', 'rm', image], capture_output=True, text=True)
        print('IMAGE_REMOVED' if result.returncode == 0 else 'IMAGE_RETAINED', image[:19], flush=True)
    if args.release_historical_backups:
        spec = importlib.util.spec_from_file_location('policy', '/usr/local/lib/agentic-class-pilot/server-backup-policy.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        complete = sorted((p for p in policy.ROOT.iterdir() if p.is_dir() and not p.is_symlink() and (p / 'BACKUP_COMPLETE').is_file()), key=lambda p: (p / 'BACKUP_COMPLETE').stat().st_mtime, reverse=True)
        assert len(complete) >= 2
        for p in complete[:2]:
            policy.verify(p)
        for name in HISTORICAL:
            p = policy.ROOT / name
            assert p.resolve().parent == policy.ROOT.resolve() and not p.is_symlink()
            if p in complete[:2]:
                continue
            print('RELEASE_BACKUP_PROTECTION', name, flush=True)
            if args.apply:
                (p / '.keep').unlink(missing_ok=True)
        policy.retain(args.apply)
    if args.apply:
        subprocess.run(['docker', 'builder', 'prune', '-f', '--filter', 'until=168h'], check=True)
    health()
    print('REMOVED_CONTAINERS', removed)
    print(run('df', '-h', '/'))


if __name__ == '__main__':
    main()
