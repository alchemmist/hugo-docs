import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('migration', Path(__file__).resolve().parents[2] / 'scripts/wiki-data.py')
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'source'
        repository = self.source / 'repository'
        repository.mkdir(parents=True)
        self.git('init')
        (repository / 'content').mkdir(parents=True)
        (repository / 'content/page.md').write_text('---\ntitle: Test\n---\nAccepted content\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.org', 'commit', '-m', 'fixture')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        snapshot = self.source / 'live/snapshots' / self.commit
        (snapshot / 'public').mkdir(parents=True)
        (snapshot / 'public/index.html').write_text('Accepted content')
        (snapshot / 'state.json').write_text(json.dumps({'base': self.commit, 'commit': self.commit, 'pending': True}))
        (self.source / 'live/current').symlink_to('/data/live/snapshots/' + self.commit)
        (self.source / 'users.sqlite3').write_bytes(b'opaque database fixture')
        (self.source / 'uploads').mkdir()
        (self.source / 'uploads/image.png').write_bytes(b'opaque upload fixture')
        self.bundle = self.root / 'backup'

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.source / 'repository'), *args], check=True, capture_output=True, text=True).stdout

    def test_round_trip_preserves_history_outbox_users_and_uploads(self):
        summary = MIGRATION.export_data(self.source, self.bundle)
        self.assertEqual(summary, {'commit': self.commit, 'pending_publications': 1})
        self.assertEqual(MIGRATION.verify(self.bundle), summary)
        target = self.root / 'new-volume'
        self.assertEqual(MIGRATION.restore(self.bundle, target), summary)
        self.assertEqual((target / 'live/current/state.json').read_text(), (self.source / 'live/snapshots' / self.commit / 'state.json').read_text())
        self.assertEqual((target / 'users.sqlite3').read_bytes(), b'opaque database fixture')
        self.assertEqual((target / 'uploads/image.png').read_bytes(), b'opaque upload fixture')
        self.assertTrue((self.source / 'live/current').is_symlink())

    def test_custom_data_root_absolute_link_is_relocated(self):
        current = self.source / 'live/current'
        current.unlink()
        current.symlink_to(self.source / 'live/snapshots' / self.commit)
        MIGRATION.export_data(self.source, self.bundle)
        target = self.root / 'custom-restored-volume'
        MIGRATION.restore(self.bundle, target)
        self.assertTrue((target / 'live/current/state.json').is_file())

    def test_corrupt_backup_is_rejected(self):
        MIGRATION.export_data(self.source, self.bundle)
        (self.bundle / 'data/uploads/image.png').write_bytes(b'corruption')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            MIGRATION.restore(self.bundle, self.root / 'new-volume')
        self.assertFalse((self.root / 'new-volume').exists())

    def test_existing_destination_is_never_overwritten(self):
        MIGRATION.export_data(self.source, self.bundle)
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            MIGRATION.restore(self.bundle, self.source)

    def test_dangling_destination_symlink_is_never_followed(self):
        MIGRATION.export_data(self.source, self.bundle)
        target = self.root / 'destination-link'
        target.symlink_to(self.root / 'missing')
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            MIGRATION.restore(self.bundle, target)
        self.assertFalse((self.root / 'missing').exists())

    def test_external_symlink_is_rejected(self):
        (self.source / 'escape').symlink_to('/etc/passwd')
        with self.assertRaisesRegex(ValueError, 'External absolute symlink'):
            MIGRATION.export_data(self.source, self.bundle)

    def test_dirty_repository_is_rejected(self):
        (self.source / 'repository/content/page.md').write_text('unsaved data')
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            MIGRATION.export_data(self.source, self.bundle)

    def test_missing_outbox_commit_is_rejected(self):
        state = self.source / 'live/snapshots' / self.commit / 'state.json'
        state.write_text(json.dumps({'commit': self.commit, 'base': 'a' * 40, 'pending': True}))
        with self.assertRaises(subprocess.CalledProcessError):
            MIGRATION.export_data(self.source, self.bundle)


if __name__ == '__main__':
    unittest.main()
