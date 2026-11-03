#!/usr/bin/python3
"""Restore into a network-isolated disposable PostgreSQL, never into application data."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

CONTAINER = 'agentic-backup-restore-20261031'
AUDIT = Path('/srv/agentic-migration-audit/20261031')


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def table_counts(container, user):
    sql = r"""SELECT format('SELECT %L, count(*) FROM %I.%I;',
        schemaname || '.' || tablename, schemaname, tablename)
        FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')
        ORDER BY schemaname, tablename
        \gexec
    """
    return subprocess.check_output(['docker', 'exec', '-i', container, 'psql', '-X', '-At',
                                   '-v', 'ON_ERROR_STOP=1', '-U', user, '-d', 'education'],
                                  input=sql.encode()).decode().strip()


def main():
    os.umask(0o077)
    backup = Path((AUDIT / 'verified-backup-path').read_text().strip())
    assert backup.parent == Path('/srv/agentedu-auto-backups') and backup.is_dir()
    spec = importlib.util.spec_from_file_location('policy', '/usr/local/lib/agentic-class-pilot/server-backup-policy.py')
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    policy.verify(backup)
    destination = AUDIT / 'restored-files'
    destination.mkdir(mode=0o700)
    counts = {}
    for name in ('teacher-data.tar.gz', 'student-runtime.tar.gz', 'object-storage.tar'):
        target = destination / name.split('.')[0]
        target.mkdir(mode=0o700)
        with tarfile.open(backup / name) as archive:
            members = archive.getmembers()
            assert members, 'Empty archive: ' + name
            archive.extractall(target, filter='data')
        counts[name] = sum(1 for p in target.rglob('*') if p.is_file())
        print('FILES_RESTORED', name, counts[name], flush=True)
    command(['git', '-c', 'safe.directory=/opt/agentic-class-pilot', '-C', '/opt/agentic-class-pilot',
             'bundle', 'verify', str(backup / 'server-source.bundle')], stdout=subprocess.DEVNULL)
    # The unique bootstrap role avoids conflicts with roles in pg_dumpall.
    command(['docker', 'run', '-d', '--name', CONTAINER, '--network', 'none', '--memory', '2g',
             '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,size=2g',
             '-e', 'POSTGRES_USER=agentic_restore_verifier', '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
             'postgres:16'], stdout=subprocess.DEVNULL)
    try:
        for _ in range(60):
            result = subprocess.run(['docker', 'exec', CONTAINER, 'pg_isready', '-U', 'agentic_restore_verifier'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Restore PostgreSQL not ready')
        with (backup / 'database-all.sql').open('rb') as source, (AUDIT / 'database-restore.log').open('wb') as log:
            command(['docker', 'exec', '-i', CONTAINER, 'psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1',
                     '-U', 'agentic_restore_verifier', '-d', 'postgres'], stdin=source, stdout=log, stderr=log)
        restored = table_counts(CONTAINER, 'agentic_restore_verifier')
        live_user = subprocess.check_output(['docker', 'exec', 'agentedu-final-database-1',
                                              'sh', '-c', 'printf %s "${POSTGRES_USER:-postgres}"']).decode()
        live = table_counts('agentedu-final-database-1', live_user)
        (AUDIT / 'restored-table-counts.txt').write_text(restored + '\n')
        (AUDIT / 'live-table-counts.txt').write_text(live + '\n')
        if restored != live:
            raise RuntimeError('Live/restored table row counts differ; inspect protected audit files')
        tables = len(restored.splitlines())
        summary = {'backup': str(backup), 'archives_restored': counts,
                   'education_tables_with_matching_row_counts': tables,
                   'database_restore': 'passed', 'network': 'none', 'application_data_modified': False}
        (AUDIT / 'restore-verification.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('RESTORE_VERIFIED', json.dumps(summary), flush=True)
    finally:
        command(['docker', 'rm', '-f', CONTAINER], stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
