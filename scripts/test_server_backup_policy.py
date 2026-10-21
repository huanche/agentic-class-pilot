"""Safety checks for destructive retention, run on Linux with unittest."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location('policy', Path(__file__).with_name('server-backup-policy.py'))
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)

class RetentionSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'backups'
        self.root.mkdir()
        policy.ROOT = self.root
        self.original_active_paths = policy.active_paths
        policy.active_paths = lambda: []

    def tearDown(self):
        policy.active_paths = self.original_active_paths
        self.temp.cleanup()

    def snapshot(self, name, age, complete=True):
        path = self.root / name
        path.mkdir()
        (path / 'data').write_bytes(b'backup')
        (path / 'SHA256SUMS').write_text(hashlib.sha256(b'backup').hexdigest() + '  ./data\n')
        if complete:
            (path / 'BACKUP_COMPLETE').touch()
        for p in list(path.iterdir()) + [path]:
            os.utime(p, (time.time() - age, time.time() - age))
        return path

    def test_keep_latest_two_protected_and_active(self):
        newest = self.snapshot('newest', 1)
        previous = self.snapshot('previous', 2)
        old = self.snapshot('old', 3)
        protected = self.snapshot('protected', 4)
        (protected / 'PROTECTED').touch()
        active = self.snapshot('active', 5)
        failed = self.snapshot('failed', 90000, False)
        recent_failed = self.snapshot('recent-failed', 3, False)
        policy.active_paths = lambda: [active / 'data']
        policy.retain(False)
        self.assertTrue(old.exists())
        policy.retain(True)
        self.assertFalse(old.exists())
        self.assertFalse(failed.exists())
        for p in (newest, previous, protected, active, recent_failed):
            self.assertTrue(p.exists())

    def test_corrupt_latest_never_deletes_old(self):
        latest = self.snapshot('latest', 1)
        self.snapshot('previous', 2)
        old = self.snapshot('old', 3)
        (latest / 'data').write_bytes(b'corrupt')
        with self.assertRaises(RuntimeError):
            policy.retain(True)
        self.assertTrue(old.exists())

    def test_external_symlink_is_untouched(self):
        self.snapshot('latest', 1)
        self.snapshot('previous', 2)
        external = Path(self.temp.name) / 'outside'
        external.mkdir()
        (self.root / 'symlink').symlink_to(external, target_is_directory=True)
        policy.retain(True)
        self.assertTrue(external.exists())

    def test_new_backup_in_use_blocks_cleanup(self):
        latest = self.snapshot('latest', 1)
        self.snapshot('previous', 2)
        old = self.snapshot('old', 3)
        policy.active_paths = lambda: [latest / 'data']
        with self.assertRaises(RuntimeError):
            policy.retain(True)
        self.assertTrue(old.exists())

if __name__ == '__main__':
    unittest.main()
