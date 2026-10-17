import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import test_live


class RuntimeSafetyTest(unittest.TestCase):
    setUp = test_live.LiveTest.setUp
    tearDown = test_live.LiveTest.tearDown
    build = test_live.LiveTest.build
    page = test_live.LiveTest.page
    update = test_live.LiveTest.update
    make_remote = test_live.LiveTest.make_remote

    def test_worker_cannot_observe_pointer_before_durable_ack(self):
        observed = []
        started = threading.Event()
        worker = None
        original = os.fsync
        root_inode = self.live.root.stat().st_ino

        def read_pending():
            started.set()
            observed.extend(self.live.pending())

        def fail_final_sync(descriptor):
            nonlocal worker
            if os.fstat(descriptor).st_ino == root_inode:
                worker = threading.Thread(target=read_pending)
                worker.start()
                self.assertTrue(started.wait(2))
                worker.join(timeout=0.1)
                self.assertTrue(worker.is_alive(), 'Worker read an unpublished transaction')
                raise OSError('Durability failure')
            return original(descriptor)

        with patch('live.os.fsync', side_effect=fail_final_sync), self.assertRaises(OSError):
            self.update('Must roll back')
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(observed, [])
        self.assertNotIn('Must roll back', self.page()['body'])

    def test_initial_build_rejects_content_root_symlink(self):
        content = self.api.WORK / self.api.PREFIX
        moved = content.with_name('elsewhere')
        content.rename(moved)
        content.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(HTTPException):
            self.real_build(self.live, self.root / 'output')

    def test_initial_build_rejects_symlinked_assets(self):
        content = self.api.WORK / self.api.PREFIX
        secret = self.root / 'secret.txt'
        secret.write_text('private')
        (content / 'leak.txt').symlink_to(secret)
        with self.assertRaises(HTTPException):
            self.real_build(self.live, self.root / 'output')

    def test_outbox_preserves_unicode_and_whitespace_filenames(self):
        self.make_remote()
        names = ('my image.png', 'диаграмма.png')
        def operation():
            for name in names:
                (self.api.WORK / self.api.PREFIX / name).write_bytes(b'asset')
            self.api.raw_git('add', '--', self.api.PREFIX)
            self.live.commit('add assets')
            return {}
        self.live.transaction(operation)()
        self.live.synchronize()
        for name in names:
            self.assertEqual((self.live.remote / self.api.PREFIX / name).read_bytes(), b'asset')
        self.assertEqual(self.live.pending(), [])

    def test_enabling_git_preserves_standalone_publications(self):
        self.make_remote()
        remote = self.live.services.REPO
        self.live.services.REPO = ''
        self.api.REPO = ''
        self.assertEqual(self.update('Standalone accepted content').status_code, 200)
        self.assertEqual(self.live.pending(), [])
        self.live.services.REPO = remote
        self.api.REPO = remote
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertIn('Standalone accepted content', (self.live.remote / self.api.PREFIX / '_index.md').read_text())
        self.assertIn('Standalone accepted content', self.page()['body'])
