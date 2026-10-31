#!/usr/bin/env python3
"""Local production backups: keep two verified snapshots; never prune active/protected data."""
import argparse
import contextlib
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path('/opt/agentic-class-pilot')
ROOT = Path('/srv/agentedu-auto-backups')
GIB = 1024 ** 3

def protected(path):
    return any((path / name).exists() for name in ('.keep', 'KEEP', 'PROTECTED', 'BACKUP_IN_PROGRESS'))

def active_paths():
    paths = []
    for fd_dir in Path('/proc').glob('[0-9]*/fd'):
        try:
            for fd in fd_dir.iterdir():
                try:
                    paths.append(Path(os.readlink(fd)))
                except (OSError, ValueError):
                    pass
        except FileNotFoundError:
            pass
        except PermissionError:
            raise RuntimeError('Run as root so active writers can be checked')
    return paths

def busy(path, opened):
    return any(p == path or path in p.parents for p in opened)

def size(path):
    return sum(p.lstat().st_blocks * 512 for p in path.rglob('*') if not p.is_symlink())

def verify(path):
    manifest = path / 'SHA256SUMS'
    if not (path / 'BACKUP_COMPLETE').is_file() or not manifest.is_file():
        raise RuntimeError('Missing completion marker/manifest: ' + path.name)
    entries = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        file = path / name.lstrip('*')
        if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(path.resolve()):
            raise RuntimeError('Unsafe/missing manifest entry in ' + path.name)
        h = hashlib.sha256()
        with file.open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                h.update(block)
        if h.hexdigest() != digest:
            raise RuntimeError('Checksum mismatch: ' + path.name + '/' + file.name)
        entries.append(file)
    if not entries:
        raise RuntimeError('Empty manifest: ' + path.name)
    actual = {p for p in path.rglob('*') if p.is_file() and p.name not in
              ('SHA256SUMS', 'BACKUP_COMPLETE', '.keep', 'KEEP', 'PROTECTED', 'BACKUP_IN_PROGRESS')}
    if set(entries) != actual:
        raise RuntimeError('Manifest does not cover every file: ' + path.name)
    print('VERIFIED', path.name, flush=True)

def retain(apply):
    opened = active_paths()
    dirs = [p for p in ROOT.iterdir() if p.is_dir() and not p.is_symlink()]
    complete = sorted((p for p in dirs if (p / 'BACKUP_COMPLETE').is_file()),
                      key=lambda p: (p / 'BACKUP_COMPLETE').stat().st_mtime, reverse=True)
    keep = complete[:2]
    # Never delete anything unless the two latest successful snapshots verify.
    if len(keep) < 2:
        print('SKIP: fewer than two complete backups')
        return
    for path in keep:
        if busy(path, opened):
            raise RuntimeError('Latest backup is still open: ' + path.name)
        verify(path)
    for path in dirs:
        if path in keep or protected(path) or busy(path, opened):
            print('KEEP', path.name)
            continue
        newest = max([path.stat().st_mtime] + [p.lstat().st_mtime for p in path.rglob('*')])
        if path not in complete and time.time() - newest < 86400:
            print('KEEP incomplete <24h', path.name)
            continue
        # Resolve and bound every deletion; do not follow directory symlinks.
        if path.parent.resolve() != ROOT.resolve() or path.is_symlink():
            raise RuntimeError('Unsafe deletion target')
        if busy(path, active_paths()):
            print('KEEP active', path.name)
            continue
        print('DELETE' if apply else 'WOULD_DELETE', path.name, flush=True)
        if apply:
            shutil.rmtree(path)
    used = size(ROOT)
    print('BACKUPS_GiB', round(used / GIB, 2), flush=True)
    if used > 20 * GIB:
        print('WARNING: backups exceed 20 GiB; protected/active backups may require review', file=sys.stderr)

def preflight():
    retain(True)
    free = shutil.disk_usage(ROOT).free
    print('FREE_GiB', round(free / GIB, 2), flush=True)
    if free < 10 * GIB:
        raise RuntimeError('Less than 10 GiB free after retention; deployment/backup blocked')

def capture(command, dest):
    with dest.open('wb') as stream:
        subprocess.run(command, stdout=stream, check=True)

def backup():
    preflight()
    path = ROOT / time.strftime('migration-%Y%m%d-%H%M%S')
    path.mkdir(mode=0o700)
    marker = path / 'BACKUP_IN_PROGRESS'
    marker.touch()
    try:
        capture(['docker', 'exec', 'agentedu-final-database-1', 'sh', '-c',
                 'exec pg_dumpall -U "${POSTGRES_USER:-postgres}"'], path / 'database-all.sql')
        capture(['tar', '-C', '/home/ubuntu/teacher-agent-data', '-czf', '-', '.'], path / 'teacher-data.tar.gz')
        # MinIO's image has no tar executable; the daemon streams this archive.
        capture(['docker', 'cp', 'agentedu-final-minio-1:/data/.', '-'], path / 'object-storage.tar')
        capture(['tar', '-C', str(REPO / 'student_agent/runtime'), '-czf', '-', '.'], path / 'student-runtime.tar.gz')
        subprocess.run(['git', '-c', 'safe.directory=' + str(REPO), '-C', str(REPO),
                        'bundle', 'create', str(path / 'server-source.bundle'), 'HEAD'], check=True)
        active_web = Path('/opt/agentic-mainland-web/current')
        if active_web.is_symlink():
            release = active_web.resolve()
            if release.parent != Path('/opt/agentic-mainland-web/releases'):
                raise RuntimeError('Unexpected active web release path')
            capture(['tar', '-C', str(release), '--exclude=.venv', '--exclude=node_modules',
                     '--exclude=runtime', '-czf', '-', '.'], path / 'active-web-source.tar.gz')
            (path / 'active-web-release.txt').write_text(str(release) + '\n')
        config = path / 'config'
        config.mkdir(mode=0o700)
        for source in [Path('/etc/agentic-class-pilot/teacher.env'),
                       Path('/home/ubuntu/teacher-prod.env'), Path('/opt/teacher-prod.env'),
                       REPO / 'teacher_agent/server-providers.yml', REPO / 'platform/.env',
                       REPO / 'platform/backend/.env']:
            if source.is_file():
                shutil.copyfile(source, config / (str(source).strip('/').replace('/', '__')))
        entries = []
        for file in sorted(path.rglob('*')):
            if not file.is_file() or file == marker:
                continue
            h = hashlib.sha256()
            with file.open('rb') as stream:
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    h.update(block)
            entries.append(h.hexdigest() + '  ./' + str(file.relative_to(path)))
        (path / 'SHA256SUMS').write_text('\n'.join(entries) + '\n')
        (path / 'BACKUP_COMPLETE').write_text(time.strftime('%Y-%m-%dT%H:%M:%S%z') + '\n')
        verify(path)
    except BaseException:
        (path / 'BACKUP_COMPLETE').unlink(missing_ok=True)
        raise
    finally:
        marker.unlink(missing_ok=True)
    retain(True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'apply', 'preflight', 'backup'])
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Run with sudo')
    os.umask(0o077)
    if ROOT.is_symlink() or ROOT.resolve() != ROOT:
        raise RuntimeError('Backup root must not contain symlinks')
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT.parent / 'backup-policy.lock').open('a') as lock:
        # Platform/student/teacher CI jobs can arrive together; serialize them
        # instead of rejecting a healthy deployment when retention is running.
        fcntl.flock(lock, fcntl.LOCK_EX)
        {'plan': lambda: retain(False), 'apply': lambda: retain(True),
         'preflight': preflight, 'backup': backup}[args.mode]()

if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print('BACKUP POLICY FAILED:', error, file=sys.stderr)
        sys.exit(1)
