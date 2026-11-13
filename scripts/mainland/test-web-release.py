#!/usr/bin/env python3
"""Exercise the real web deployer on Linux with disposable files and fake services.

Run as root so owner/mode checks are real. All subprocess entry points and health
requests are replaced before deploy(); no Docker, systemctl or database is used.
"""
import json
import io
import os
from pathlib import Path
import shlex
import subprocess
import shutil
import sys
import tempfile
import tarfile
import time
from types import SimpleNamespace
import unittest


SOURCE = globals().get("DEPLOY_SOURCE") or Path(__file__).with_name("agentic-web-deploy").read_text()


class WebReleaseTest(unittest.TestCase):
    def test_release_environment_accepts_only_private_root_owned_configuration(self):
        path = self.root / 'learning-auth.env'
        original_path = self.ns['Path']
        self.ns['Path'] = lambda value: path if str(value) == '/etc/agentic-class-pilot/student-learning-auth.env' else original_path(value)
        self.assertEqual(self.ns['release_environment']('agentic-student'), self.env)
        path.write_text('PLATFORM_TO_STUDENT_KEY=' + 'k' * 64 + '\nSTUDENT_URL=http://127.0.0.1:8000\n')
        path.chmod(0o600)
        merged = self.ns['release_environment']('agentic-student')
        self.assertEqual(merged['PLATFORM_TO_STUDENT_KEY'], 'k' * 64)
        self.assertEqual(merged['STUDENT_DATABASE_URL'], self.env['STUDENT_DATABASE_URL'])
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
            self.ns['release_environment']('agentic-student')
        path.chmod(0o600)
        path.write_text('DATABASE_URL=not-allowed\n')
        with self.assertRaisesRegex(RuntimeError, 'Invalid'):
            self.ns['release_environment']('agentic-student')
        path.unlink()
        real = self.root / 'real-auth.env'
        real.write_text('PLATFORM_TO_STUDENT_KEY=' + 'k' * 64 + '\n')
        real.chmod(0o600)
        path.symlink_to(real)
        with self.assertRaisesRegex(RuntimeError, 'Untrusted'):
            self.ns['release_environment']('agentic-student')

    def setUp(self):
        self.assertEqual(os.geteuid(), 0, "Use sudo for the isolated ownership checks")
        self.temp = tempfile.TemporaryDirectory(prefix="agentic-web-release-test-")
        self.root = Path(self.temp.name)
        self.ns = {"__name__": "sandbox_deployer"}
        exec(compile(SOURCE, "sandbox_deployer", "exec"), self.ns)
        self.real_grouped_call = self.ns["_call_process_group"]
        self.real_live_environment = self.ns["live_environment"]
        self.base = self.root / "opt/agentic-mainland-web"
        self.old = self.base / "releases" / ("b" * 40)
        self.sha = "a" * 40
        self.target = self.base / "releases" / self.sha
        self.frozen = self.root / "run/agentic-web-migration"
        self.events = []
        self.revision = "rec12"
        self.pids = {"agentic-platform": "0", "agentic-student": "0"}
        self.health = [True]
        self.fail_ready = False
        self.fail_start = False
        self.archive = None
        self.uv_directories = []
        self.env = {"STUDENT_DATABASE_URL": "postgresql://unused@127.0.0.1/unused"}
        def mapped(value):
            value = str(value)
            return self.root / value.lstrip("/") if value.startswith("/") else Path(value)
        self.ns.update(Path=mapped, BASE=self.base, OLD=self.root / "opt/old", FROZEN=self.frozen,
                       output=self.output, call=self.call, healthy=self.healthy,
                       live_environment=lambda unit: self.env.copy(),
                       sys=SimpleNamespace(argv=["deployer", self.sha]))
        for path in (self.old, self.target, self.root / "run/lock"):
            path.mkdir(parents=True)
        for unit in self.pids:
            (self.root / "etc/systemd/system" / (unit + ".service.d")).mkdir(parents=True)
        (self.base / "current").symlink_to(self.old)
        self.write("etc/agentic-class-pilot/web-deploy-enabled", "", 0o600)
        self.write("var/lib/agentic-class-pilot/prepared-images/web-" + self.sha + ".json",
                   json.dumps({"image": self.ns["REPO"] + ":web-" + self.sha, "id": "sha256:test"}), 0o600)
        receipt = {"sha": self.sha, "image_id": "sha256:test", "reference": str(self.old)}
        self.write("var/lib/agentic-class-pilot/staged-web/" + self.sha + ".json", json.dumps(receipt), 0o600)
        (self.root / "var/lib/agentic-class-pilot/staged-web").chmod(0o700)
        (self.target / "manifest.json").write_text(json.dumps({"sha": self.sha}))
        (self.target / "student_agent").mkdir()
        (self.target / "student_agent/RELEASE_COMPATIBILITY.json").write_text(
            '{"studentDataFormat":"student-reliable-records-v1"}')

    def write(self, name, text, mode):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)
        return path

    def output(self, args, **kwargs):
        self.events.append(tuple(args))
        if args == ["hostname"]:
            return "VM-0-4-ubuntu"
        if args[:3] == ["docker", "image", "inspect"]:
            return "sha256:test"
        if args[:2] == ["systemctl", "show"] and "MainPID" in args:
            return self.pids[args[2]]
        if args[-2:] == ["alembic", "current"]:
            return self.revision
        if args[-2:] == ["alembic", "heads"]:
            return "rec12 (head)"
        raise AssertionError("Unexpected output command: " + repr(args))

    def call(self, args, **kwargs):
        self.events.append(tuple(args))
        if args[:2] == ['docker', 'create'] or args[:2] == ['docker', 'rm'] or args[0] == 'chown':
            return
        if args[:2] == ['docker', 'cp']:
            self.assertIsNotNone(self.archive)
            kwargs['stdout'].write(self.archive)
            return
        if args[:5] == ['runuser', '-u', 'ubuntu', '--', self.ns['UV']]:
            self.assertIn(kwargs.get('cwd'), [self.target / 'platform', self.target / 'student_agent'],
                          'uv must not inherit the CI SSH user home as its working directory')
            self.uv_directories.append(kwargs['cwd'])
            return
        if args[-1] == "backend.infrastructure.release_check":
            if self.fail_ready:
                raise subprocess.CalledProcessError(1, "simulated readiness")
            return
        if args[0] == "/usr/local/sbin/agentic-mainland-backup":
            return
        if args[:2] == ["systemctl", "daemon-reload"]:
            return
        if args[0] == "systemctl" and args[1] in {"stop", "start", "restart"}:
            for unit in args[2:]:
                self.pids[unit] = "0" if args[1] == "stop" else "123"
            if args[1] == "start" and self.fail_start:
                raise subprocess.CalledProcessError(1, "simulated start")
            return
        raise AssertionError("Unexpected mutation command: " + repr(args))

    def healthy(self):
        return self.health.pop(0) if len(self.health) > 1 else self.health[0]

    def mutations(self):
        return [event for event in self.events if event[0] in {"systemctl", "/usr/local/sbin/agentic-mainland-backup"}
                and event[1] != "show"]

    def tearDown(self):
        try:
            os.close(9)
        except OSError:
            pass
        self.temp.cleanup()

    def test_stage_only_does_not_check_or_mutate_the_live_database_or_services(self):
        self.ns["sys"].argv = ["deployer", "--stage-only", self.sha]
        self.ns["deploy"]()
        self.assertEqual(self.mutations(), [])
        self.assertFalse(any("alembic" in event for event in self.events))
        self.assertEqual((self.base / "current").resolve(), self.old)

    def test_fresh_dependency_checks_use_the_release_directory_not_the_ci_home(self):
        shutil.rmtree(self.target)
        (self.root / 'var/lib/agentic-class-pilot/staged-web' / (self.sha + '.json')).unlink()
        files = {'manifest.json': json.dumps({'sha': self.sha}),
                 'platform/backend/app/frontend/index.html': 'test',
                 'student_agent/frontend/out/index.html': 'test',
                 'platform/uv.lock': 'test', 'platform/pyproject.toml': 'test',
                 'platform/backend/pyproject.toml': 'test',
                 'student_agent/backend/requirements.txt': 'test'}
        for app in ('platform', 'student_agent'):
            (self.old / app / '.venv/lib/python3.12/site-packages').mkdir(parents=True)
        for name, value in files.items():
            if name.endswith(('toml', 'lock', 'requirements.txt')):
                old_file = self.old / name
                old_file.parent.mkdir(parents=True, exist_ok=True)
                old_file.write_text(value)
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode='w') as tar:
            for name, value in files.items():
                data = value.encode()
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
        self.archive = archive.getvalue()
        self.ns['sys'].argv = ['deployer', '--stage-only', self.sha]
        self.ns['deploy']()
        self.assertEqual(self.uv_directories, [self.target / 'platform', self.target / 'student_agent'])
        self.assertEqual((self.base / 'current').resolve(), self.old)
        self.assertTrue((self.root / 'var/lib/agentic-class-pilot/staged-web' / (self.sha + '.json')).is_file())

        # A changed lock/requirements file must update a copy of the active
        # environment instead of downloading every dependency from scratch.
        shutil.rmtree(self.target)
        (self.root / 'var/lib/agentic-class-pilot/staged-web' / (self.sha + '.json')).unlink()
        (self.old / 'platform/uv.lock').write_text('previous lock')
        (self.old / 'student_agent/backend/requirements.txt').write_text('previous requirements')
        for app in ('platform', 'student_agent'):
            (self.old / app / '.venv/reused-marker').write_text('active environment')
        self.events.clear()
        self.uv_directories.clear()
        self.ns['deploy']()
        for app in ('platform', 'student_agent'):
            self.assertEqual((self.target / app / '.venv/reused-marker').read_text(), 'active environment')
        uv_calls = [event for event in self.events if event[:5] ==
                    ('runuser', '-u', 'ubuntu', '--', self.ns['UV'])]
        self.assertTrue(any('sync' in event for event in uv_calls))
        self.assertTrue(any(event[5:7] == ('pip', 'install') for event in uv_calls))
        self.assertFalse(any(event[5] == 'venv' for event in uv_calls))
        self.assertIn(str(self.target / 'platform/.venv/bin/python'),
                      next(event for event in uv_calls if 'sync' in event))
        self.assertEqual((self.base / 'current').resolve(), self.old)

    def test_command_timeout_terminates_child_processes(self):
        marker = self.root / 'orphan-marker'
        child = f'(sleep 2; touch {shlex.quote(str(marker))}) & wait'
        with self.assertRaises(subprocess.TimeoutExpired):
            self.real_grouped_call(['bash', '-c', child], timeout=0.2)
        time.sleep(2.2)
        self.assertFalse(marker.exists(), 'a timed-out command left a descendant running')

    def test_revision_mismatch_never_stops_services(self):
        self.revision = "pub10"
        with self.assertRaisesRegex(RuntimeError, "migration requires"):
            self.ns["deploy"]()
        self.assertEqual(self.mutations(), [])

    def test_failed_readiness_never_stops_services(self):
        self.fail_ready = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.ns["deploy"]()
        self.assertEqual(self.mutations(), [])

    def test_first_upgrade_refuses_active_old_writers(self):
        self.pids["agentic-student"] = "123"
        with self.assertRaisesRegex(RuntimeError, "frozen maintenance window"):
            self.ns["deploy"]()
        self.assertEqual(self.mutations(), [])

    def test_typed_dialogue_upgrade_refuses_active_legacy_reader_before_backup(self):
        (self.old / 'student_agent').mkdir()
        legacy = {'studentDataFormat': 'student-reliable-records-v1'}
        (self.old / 'student_agent/RELEASE_COMPATIBILITY.json').write_text(json.dumps(legacy))
        typed = {**legacy, 'teachingDialogueReadVersions': [3, 4],
                 'teachingDialogueWriteVersions': [3, 4]}
        (self.target / 'student_agent/RELEASE_COMPATIBILITY.json').write_text(json.dumps(typed))
        self.pids['agentic-student'] = '123'
        with self.assertRaisesRegex(RuntimeError, 'not rollback-compatible'):
            self.ns['deploy']()
        self.assertEqual(self.mutations(), [])
        self.assertEqual((self.base / 'current').resolve(), self.old)

    def test_first_upgrade_starts_only_after_checks_and_backup(self):
        self.ns["deploy"]()
        self.assertEqual((self.base / "current").resolve(), self.target)
        self.assertIn('STUDENT_DYNAMIC_PILOT_SCOPES="[]"', (self.target / "student-start.sh").read_text())
        self.assertEqual([event[0:2] for event in self.mutations()], [
            ("/usr/local/sbin/agentic-mainland-backup", "--locked"),
            ("systemctl", "stop"), ("systemctl", "daemon-reload"), ("systemctl", "start")])

    def test_first_upgrade_failure_stops_without_restarting_old_writer(self):
        self.fail_start = True
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_CODE_ROLLBACK_BLOCKED"):
            self.ns["deploy"]()
        self.assertEqual(set(self.pids.values()), {"0"})
        self.assertNotIn(("systemctl", "restart"), [event[:2] for event in self.events])

    def test_compatible_health_failure_restores_previous_release(self):
        (self.old / "student_agent").mkdir()
        (self.old / "student_agent/RELEASE_COMPATIBILITY.json").write_text(
            (self.target / "student_agent/RELEASE_COMPATIBILITY.json").read_text())
        self.health = [False, True]
        with self.assertRaisesRegex(RuntimeError, "failed health check"):
            self.ns["deploy"]()
        self.assertEqual((self.base / "current").resolve(), self.old)
        self.assertIn(("systemctl", "restart"), [event[:2] for event in self.events])

    def test_failed_first_activation_retains_a_verified_environment_for_repair(self):
        self.fail_start = True
        self.frozen.mkdir(mode=0o700)
        for unit in self.pids:
            path = self.frozen / (unit + '.json')
            path.write_text(json.dumps({"reference": str(self.old), "environment": self.env}))
            path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "UNSAFE_CODE_ROLLBACK_BLOCKED"):
            self.ns["deploy"]()
        self.assertEqual((self.base / "current").resolve(), self.target)
        self.assertEqual(self.real_live_environment("agentic-student")["STUDENT_DATABASE_URL"],
                         self.env["STUDENT_DATABASE_URL"])
        receipt = self.root / "var/lib/agentic-class-pilot/staged-web" / (self.sha + ".json")
        receipt.chmod(0o666)
        with self.assertRaises(RuntimeError):
            self.real_live_environment("agentic-student")

    def test_capture_uses_root_only_files_and_refuses_overwrite(self):
        self.pids = dict.fromkeys(self.pids, "123")
        self.ns["sys"].argv = ["deployer", "--capture-migration-environment"]
        self.ns["deploy"]()
        self.assertEqual(self.frozen.stat().st_mode & 0o777, 0o700)
        for unit in self.pids:
            path = self.frozen / (unit + ".json")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["reference"], str(self.old))
        with self.assertRaises(FileExistsError):
            self.ns["deploy"]()
        self.assertEqual(self.mutations(), [])


if __name__ == "__main__":
    unittest.main(argv=["test-web-release"], verbosity=2)
