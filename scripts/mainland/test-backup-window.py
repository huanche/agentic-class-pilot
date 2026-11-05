#!/usr/bin/env python3
"""Exercise the backup shell's writer freeze/restore using only disposable files and fake services."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).with_name('agentic-mainland-backup').read_text()


class BackupWindowTest(unittest.TestCase):
    def exercise(self, fail):
        with tempfile.TemporaryDirectory(prefix='backup-window-test-') as name:
            root = Path(name)
            commands = root / 'bin'
            commands.mkdir()
            for item in ['run/lock', 'srv/agentedu-auto-backups', 'usr/local/libexec', 'usr/local/lib/agentic-class-pilot']:
                (root / item).mkdir(parents=True, exist_ok=True)
            statefile = root / 'state.json'
            statefile.write_text(json.dumps({'paused': [], 'events': []}))
            stub = r"""#!/usr/bin/python3
import json,os,sys
from pathlib import Path
statefile=Path(os.environ['TEST_STATE']);state=json.loads(statefile.read_text())
args=sys.argv[1:];tool=Path(sys.argv[0]).name
state['events'].append([tool,*args])
if tool=='docker':
 if args[:2]==['ps','-q']:print('agentic-teacher-prod agentedu-final-minio-1 extra-writer readonly-reader')
 elif args[0]=='inspect':
  if '-f' in args:
   name=args[-1];print(str(name in state['paused']).lower() if 'Paused' in args[args.index('-f')+1] else 'true')
  else:
   print(json.dumps([{'Name':'/'+n,'Mounts':[{'RW':n!='readonly-reader','Source':os.environ['TEST_TEACHER_DATA']}]} for n in args[1:]]))
 elif args[0]=='pause':state['paused'].append(args[1])
 elif args[0]=='unpause':state['paused'].remove(args[1])
elif tool=='curl':print('200')
statefile.write_text(json.dumps(state))
"""
            for command in ['docker', 'systemctl', 'curl']:
                path = commands / command
                path.write_text(stub)
                path.chmod(0o755)
            wait = root / 'usr/local/libexec/agentic-teacher-wait-idle.sh'
            wait.write_text('#!/bin/bash\nexit 0\n')
            policy = root / 'usr/local/lib/agentic-class-pilot/server-backup-policy.py'
            policy.write_text("import os,sys\nfrom pathlib import Path\nif os.environ.get('TEST_FAIL')=='1':sys.exit(7)\np=Path(os.environ['TEST_BACKUPS'])/'migration-test';p.mkdir();(p/'BACKUP_COMPLETE').touch()\n")
            text = SOURCE
            for prefix in ['/run/', '/srv/', '/usr/local/', '/etc/', '/opt/agentic-class-pilot', '/home/ubuntu/teacher-agent-data']:
                text = text.replace(prefix, str(root) + prefix)
            assert text.startswith('#!/bin/bash\n')
            text = text.replace('#!/bin/bash\n', '#!/bin/bash\nexport PATH=' + str(commands) + ':/usr/sbin:/usr/bin:/sbin:/bin\n', 1)
            text = text.replace('[[ $EUID == 0 && $(hostname) == VM-0-4-ubuntu ]] || exit 1', 'true # isolated host/owner guard fixture')
            script = root / 'backup.sh'
            script.write_text(text)
            env = os.environ | {'TEST_STATE': str(statefile), 'TEST_TEACHER_DATA': str(root) + '/home/ubuntu/teacher-agent-data',
                                'TEST_BACKUPS': str(root / 'srv/agentedu-auto-backups'), 'TEST_FAIL': str(int(fail))}
            result = subprocess.run(['bash', str(script)], cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 7 if fail else 0, result.stderr)
            state = json.loads(statefile.read_text())
            self.assertEqual(state['paused'], [])
            events = state['events']
            self.assertIn(['docker', 'pause', 'extra-writer'], events)
            self.assertIn(['docker', 'unpause', 'extra-writer'], events)
            self.assertNotIn(['docker', 'pause', 'readonly-reader'], events)
            self.assertNotIn(['docker', 'pause', 'agentic-teacher-prod'], events)
            self.assertNotIn(['docker', 'pause', 'agentedu-final-minio-1'], events)
            self.assertLess(events.index(['docker', 'pause', 'extra-writer']), events.index(['docker', 'stop', '-t', '60', 'agentic-teacher-prod']))
            self.assertIn(['systemctl', 'start', 'agentic-platform', 'agentic-student', 'agentic-teacher-forward'], events)

    def test_success_freezes_all_extra_writers_and_restores_original_processes(self):
        self.exercise(False)

    def test_backup_failure_also_resumes_extra_writers_and_services(self):
        self.exercise(True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
