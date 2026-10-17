import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))


def command(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / 'template'
        (self.template / 'content').mkdir(parents=True)
        (self.template / 'content/_index.md').write_text('---\ntitle: Home\n---\n\nInitial\n')
        self.env = patch.dict(os.environ, LIVE_MODE='1', GIT_REPOSITORY=str(self.root / 'offline.git'), WIKI_DATA_DIR=str(self.root / 'data'), PUBLIC_ORIGIN='http://localhost:8080', CONTENT_PREFIX='content', LIVE_STATE_DIR=str(self.root / 'live'), LIVE_TEMPLATE_DIR=str(self.template), WORK_DIR=str(self.root / 'work'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('live_editor_test', Path(__file__).parents[1] / 'app.py')
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.live = self.api.LIVE
        self.real_build = type(self.live).build
        self.build_patch = patch.object(type(self.live), 'build', lambda live, destination: self.build(live, destination))
        self.build_patch.start()
        self.live.initialize()
        self.api.AUTH.create_user('admin', 'test-password', 'admin')
        self.client = TestClient(self.api.app, base_url=self.api.ORIGIN)
        login = self.client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password'}, headers={'Origin': self.api.ORIGIN})
        self.assertEqual(login.status_code, 200, login.text)
        csrf = self.client.get('/api/editor/session').json()['csrf_token']
        self.headers = {'Origin': self.api.ORIGIN, 'X-CSRF-Token': csrf}

    def build(self, live, destination):
        (destination / 'public').mkdir()
        (destination / 'public/index.html').write_text((self.api.WORK / 'content/_index.md').read_text())

    def tearDown(self):
        self.client.close()
        self.build_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def page(self):
        return self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()

    def update(self, body='Changed'):
        return self.client.post('/api/editor/batch', json={'pages': [dict(self.page(), body=body)]}, headers=self.headers)

    def make_remote(self):
        remote = self.root / 'origin.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        command(self.api.WORK, 'push', str(remote), 'HEAD:refs/heads/main')
        self.api.REPO = str(remote)
        self.live.services.REPO = str(remote)
        return remote

    def test_publish_without_network_and_restart(self):
        raw = self.api.raw_git
        def offline(*args, **kwargs):
            self.assertNotIn(args[0], ('fetch', 'clone', 'push'))
            return raw(*args, **kwargs)
        with patch.object(self.live.services, 'raw_git', side_effect=offline):
            result = self.update()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn('Changed', self.client.get('/site/').text)
            self.assertEqual(self.page()['body'], 'Changed')
            self.live.started = False
            self.live.initialize()
            self.assertEqual(self.page()['body'], 'Changed')
            self.assertEqual(len(self.live.pending()), 1)

    def test_git_disabled_publishes_without_outbox(self):
        self.api.REPO = ''
        self.live.services.REPO = ''
        response = self.update('Local only')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.page()['body'], 'Local only')
        self.assertEqual(self.live.pending(), [])
        self.assertIn('Local only', self.client.get('/site/').text)

    def test_batch_conflict_rolls_back_all(self):
        before = self.page()
        result = self.client.post('/api/editor/batch', json={'pages': [dict(before, body='Lost'), {'path': 'missing.md', 'title': 'Bad', 'body': 'Bad', 'revision': '0' * 40}]}, headers=self.headers)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.page(), before)
        self.assertEqual(len(self.live.pending()), 0)
        self.assertNotIn('Lost', self.client.get('/site/').text)

    def test_failed_render_never_acknowledges_or_changes_content(self):
        before = self.page()
        with patch.object(self.live, 'build', side_effect=self.api.HTTPException(422, 'Broken link')):
            response = self.update()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.page(), before)
        self.assertFalse(self.live.pending())

    def test_git_conflict_preserves_live_and_remote(self):
        self.make_remote()
        self.live.synchronize()
        remote_page = self.live.remote / 'content/_index.md'
        remote_page.write_text('---\ntitle: Remote\n---\n\nRemote\n')
        command(self.live.remote, 'add', '.')
        command(self.live.remote, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'remote change')
        command(self.live.remote, 'push', 'origin', 'main')
        self.assertEqual(self.update('Local').status_code, 200)
        self.live.synchronize()
        self.assertEqual(self.page()['body'], 'Local')
        self.assertIn('Remote', remote_page.read_text())
        self.assertIn('Concurrent Git changes', self.live.pending()[0][1]['error'])

    def test_outbox_preserves_unrelated_files_and_exact_bytes(self):
        self.make_remote()
        self.live.synchronize()
        unrelated = self.live.remote / 'README.md'
        unrelated.write_text('External change')
        command(self.live.remote, 'add', '.')
        command(self.live.remote, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'other change')
        command(self.live.remote, 'push', 'origin', 'main')
        self.assertEqual(self.update('Exact trailing\n\n').status_code, 200)
        self.live.synchronize()
        self.assertEqual(unrelated.read_text(), 'External change')
        self.assertEqual((self.live.remote / 'content/_index.md').read_bytes(), (self.api.WORK / 'content/_index.md').read_bytes())
        self.assertFalse(self.live.pending())

    def test_public_site_does_not_expose_editor_or_sources(self):
        public = TestClient(self.api.app, base_url=self.api.ORIGIN)
        self.assertEqual(public.get('/site/').status_code, 200)
        self.assertEqual(public.get('/healthz').status_code, 200)
        self.assertEqual(public.get('/api/editor/pages?path=_index.md').status_code, 401)
        self.assertEqual(public.get('/site/.git/config').status_code, 404)
        self.assertEqual(public.post('/site/').status_code, 403)
        (self.live.current / 'public/leak').symlink_to(self.api.WORK / 'content/_index.md')
        self.assertEqual(public.get('/site/leak').status_code, 404)

    def test_multipage_publication_is_one_pending_patch(self):
        response = self.client.post('/api/editor/batch', json={'pages': [dict(self.page(), body='Home edit'), {'section': '', 'slug': 'second', 'title': 'Second', 'body': 'Second edit'}]}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['pages']), 2)
        self.assertEqual(len(self.live.pending()), 1)
        self.assertIn('Home edit', self.client.get('/site/').text)
        second = self.client.get('/api/editor/pages', params={'path': 'second.md'}).json()
        self.assertEqual(second['body'], 'Second edit')

    def test_new_template_renders_accepted_content_without_losing_outbox(self):
        self.assertEqual(self.update('Accepted').status_code, 200)
        previous = self.live.current.resolve()
        self.live.started = False
        def newer(destination):
            (destination / 'public').mkdir()
            (destination / 'public/index.html').write_text('New template: ' + (self.api.WORK / 'content/_index.md').read_text())
        with patch.object(self.live, 'build', side_effect=newer):
            self.live.initialize()
        self.assertNotEqual(previous, self.live.current.resolve())
        self.assertIn('New template:', self.client.get('/site/').text)
        self.assertIn('Accepted', self.client.get('/site/').text)
        self.assertEqual(len(self.live.pending()), 1)

    def test_lost_push_ack_is_idempotently_recovered(self):
        self.make_remote()
        self.live.synchronize()
        self.assertEqual(self.update('Accepted').status_code, 200)
        raw = self.api.raw_git
        def lost(*args, **kwargs):
            result = raw(*args, **kwargs)
            if args[0] == 'push':
                raise RuntimeError('Lost acknowledgment')
            return result
        with patch.object(self.live.services, 'raw_git', side_effect=lost):
            with self.assertRaises(RuntimeError):
                self.live.synchronize()
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertFalse(self.live.pending())
        self.assertEqual(self.page()['body'], 'Accepted')

    def test_new_save_while_previous_push_runs_remains_pending(self):
        self.make_remote()
        self.live.synchronize()
        self.assertEqual(self.update('First').status_code, 200)
        raw = self.api.raw_git
        published = []
        def interleave(*args, **kwargs):
            result = raw(*args, **kwargs)
            if args[0] == 'push' and not published:
                published.append(True)
                self.assertEqual(self.update('Second').status_code, 200)
            return result
        with patch.object(self.live.services, 'raw_git', side_effect=interleave):
            self.live.synchronize()
        self.assertEqual(self.page()['body'], 'Second')
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertFalse(self.live.pending())
        self.assertEqual(self.page()['body'], 'Second')

    def test_move_deletes_old_remote_path(self):
        self.make_remote()
        self.live.synchronize()
        page = self.client.post('/api/editor/pages', json={'section': '', 'slug': 'note', 'title': 'Note', 'body': 'Body'}, headers=self.headers)
        self.assertEqual(page.status_code, 200)
        tree = self.client.get('/api/editor/tree').json()
        folder = self.client.post('/api/editor/folders', json={'parent': '', 'slug': 'folder', 'title': 'Folder', 'revision': tree['revision']}, headers=self.headers)
        self.assertEqual(folder.status_code, 200, folder.text)
        self.live.synchronize()
        moved = self.client.post('/api/editor/move', json={'source': 'note.md', 'target_parent': 'folder', 'revision': folder.json()['revision']}, headers=self.headers)
        self.assertEqual(moved.status_code, 200, moved.text)
        self.live.synchronize()
        self.assertFalse((self.live.remote / 'content/note.md').exists())
        self.assertTrue((self.live.remote / 'content/folder/note.md').exists())

    def test_build_preserves_nested_theme_content_directory(self):
        partial = self.template / '_vendor/theme/layouts/partials/content/head.html'
        partial.parent.mkdir(parents=True)
        partial.write_text('Theme partial')
        destination = self.root / 'render-check'
        destination.mkdir()
        def render(args, **kwargs):
            source = Path(args[args.index('--source') + 1])
            self.assertEqual((source / '_vendor/theme/layouts/partials/content/head.html').read_text(), 'Theme partial')
            self.assertEqual(source, self.template)
            self.assertEqual(Path(args[args.index('--contentDir') + 1]), self.api.WORK / self.api.PREFIX)
            self.assertEqual(kwargs['env']['HUGO_RESOURCEDIR'], str(self.live.root / 'hugo-resources'))
            self.assertEqual(kwargs['env']['HUGO_MODULE_PROXY'], 'off')
            self.assertEqual(kwargs['env']['GOPROXY'], 'off')
            (destination / 'public').mkdir()
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch('live.subprocess.run', side_effect=render):
            self.real_build(self.live, destination)

    def test_restart_rebuilds_missing_generated_files_from_durable_content(self):
        response = self.update('Durably accepted')
        self.assertEqual(response.status_code, 200, response.text)
        publication = response.json()['commit']
        rendered = self.live.current / 'public'
        (rendered / 'index.html').write_text('Truncated')
        (rendered / 'version.json').unlink()
        self.live.started = False
        self.live.initialize()
        self.assertIn('Durably accepted', self.client.get('/site/').text)
        self.assertEqual(self.page()['body'], 'Durably accepted')
        self.assertEqual(self.client.get('/site/version.json').json()['source_sha'], publication)
        self.assertEqual(len(self.live.pending()), 1)
        self.assertEqual(self.live.pending()[0][1]['commit'], publication)
        shutil.rmtree(self.live.current / 'public')
        self.live.started = False
        self.live.initialize()
        self.assertIn('Durably accepted', self.client.get('/site/').text)
        self.assertEqual(len(self.live.pending()), 1)

    def batch(self, pages, operations, revision=None):
        revision = revision or self.client.get('/api/editor/tree').json()['revision']
        return self.client.post('/api/editor/batch', json={'pages': pages, 'operations': operations, 'tree_revision': revision}, headers=self.headers)

    def test_batch_edits_moves_and_references_publish_once(self):
        page = {'slug': 'note', 'title': 'Note', 'body': 'Original'}
        self.assertEqual(self.batch([page], []).status_code, 200)
        self.make_remote()
        self.live.synchronize()
        edited = self.client.get('/api/editor/pages?path=note.md').json()
        edited['body'] = 'Edited {{< relref "#section" >}}'
        home = dict(self.page(), body='See {{< relref "note.md#section" >}}')
        with patch.object(self.live, 'build', wraps=self.live.build) as build:
            result = self.batch([edited, home], [
                {'type': 'folder', 'parent': '', 'slug': 'folder', 'title': 'Folder'},
                {'type': 'move', 'source': 'note.md', 'target_parent': 'folder'},
            ])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(len(self.live.pending()), 1)
        saved = result.json()['pages'][0]
        self.assertEqual(saved['original_path'], 'note.md')
        self.assertEqual(saved['path'], 'folder/note.md')
        self.assertEqual(saved['url'], self.api.ORIGIN + '/folder/note/')
        moved = self.client.get('/api/editor/pages?path=folder/note.md').json()
        self.assertEqual(saved['revision'], moved['revision'])
        self.assertEqual(saved['body'], moved['body'])
        self.assertEqual(saved['title'], moved['title'])
        self.assertIn('Edited', moved['body'])
        self.assertIn('/folder/note.md#section', moved['body'])
        self.assertIn('/folder/note.md#section', self.page()['body'])
        self.assertEqual(self.client.get('/api/editor/pages?path=note.md').status_code, 404)
        self.live.synchronize()
        self.assertFalse((self.live.remote / 'content/note.md').exists())
        self.assertIn('Edited', (self.live.remote / 'content/folder/note.md').read_text())

    def test_batch_new_page_nested_folders_and_order(self):
        result = self.batch([{'slug': 'note', 'title': 'Note', 'body': 'New'}], [
            {'type': 'folder', 'parent': '', 'slug': 'first', 'title': 'First'},
            {'type': 'folder', 'parent': '', 'slug': 'second', 'title': 'Second'},
            {'type': 'move', 'source': 'note.md', 'target_parent': 'first'},
            {'type': 'move', 'source': 'first', 'target_parent': 'second'},
            {'type': 'folder', 'parent': '', 'slug': 'third', 'title': 'Third'},
            {'type': 'move', 'source': 'third', 'target_parent': '', 'before': 'second'},
        ])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['pages'][0]['path'], 'second/first/note.md')
        self.assertEqual([node['id'] for node in result.json()['nodes']], ['third', 'second'])
        self.assertEqual(len(self.live.pending()), 1)
        self.assertEqual(result.json()['revision'], self.client.get('/api/editor/tree').json()['revision'])

    def test_structure_only_batch_and_missing_revision(self):
        operation = {'type': 'folder', 'parent': '', 'slug': 'folder', 'title': 'Folder'}
        rejected = self.client.post('/api/editor/batch', json={'pages': [], 'operations': [operation]}, headers=self.headers)
        self.assertEqual(rejected.status_code, 422)
        accepted = self.batch([], [operation])
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()['pages'], [])
        self.assertEqual(len(self.live.pending()), 1)

    def test_combined_batch_invalid_move_rolls_back_content_and_folders(self):
        before = self.page()
        tree = self.client.get('/api/editor/tree').json()
        result = self.batch([dict(before, body='Must roll back')], [
            {'type': 'folder', 'parent': '', 'slug': 'folder', 'title': 'Folder'},
            {'type': 'move', 'source': 'folder', 'target_parent': 'folder'},
        ])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.page(), before)
        self.assertEqual(self.client.get('/api/editor/tree').json(), tree)
        self.assertFalse(self.live.pending())
        self.assertNotIn('Must roll back', self.client.get('/site/').text)

    def test_batch_base_conflict_changes_nothing(self):
        before = self.page()
        result = self.batch([dict(before, body='Lost')], [
            {'type': 'folder', 'parent': '', 'slug': 'folder', 'title': 'Folder'},
        ], revision='0' * 40)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.page(), before)
        self.assertFalse(self.live.pending())

    def test_batch_new_page_before_existing_edit_does_not_self_conflict(self):
        self.assertEqual(self.batch([{'slug': 'old', 'title': 'Old', 'body': 'Old'}], []).status_code, 200)
        target = self.api.WORK / 'content/old.md'
        metadata, body = self.api.parse(target.read_text())
        metadata['weight'] = 99
        self.api.write_markdown(target, metadata, body)
        self.api.raw_git('add', '.')
        self.api.raw_git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'different weight')
        old = self.client.get('/api/editor/pages?path=old.md').json()
        result = self.batch([{'slug': 'new', 'title': 'New', 'body': 'New'}, dict(old, body='Edited')], [])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/editor/pages?path=old.md').json()['body'], 'Edited')

    def test_edited_folder_index_tracks_ancestor_move(self):
        result = self.batch([], [
            {'type': 'folder', 'parent': '', 'slug': 'source', 'title': 'Source'},
            {'type': 'folder', 'parent': '', 'slug': 'target', 'title': 'Target'},
        ])
        self.assertEqual(result.status_code, 200, result.text)
        page = self.client.get('/api/editor/pages?path=source/_index.md').json()
        result = self.batch([dict(page, title='Changed title', body='Folder content')], [
            {'type': 'move', 'source': 'source', 'target_parent': 'target'},
        ])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['pages'][0]['path'], 'target/source/_index.md')
        self.assertEqual(result.json()['nodes'][0]['children'][0]['title'], 'Changed title')
        self.assertEqual(self.client.get('/api/editor/pages?path=target/source/_index.md').json()['body'], 'Folder content')

    def test_batch_stale_page_prevents_all_operations(self):
        before = self.page()
        result = self.batch([dict(before, revision='0' * 40)], [
            {'type': 'folder', 'parent': '', 'slug': 'folder', 'title': 'Folder'},
        ])
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(self.page(), before)
        self.assertEqual(self.client.get('/api/editor/tree').json()['nodes'], [])
        self.assertFalse(self.live.pending())

    def test_batch_delete_recursive_after_edit_and_move(self):
        result = self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Old'}], [
            {'type': 'folder', 'slug': 'folder', 'title': 'Folder'},
            {'type': 'move', 'source': 'note.md', 'target_parent': 'folder'},
        ])
        self.assertEqual(result.status_code, 200, result.text)
        asset = self.api.WORK / 'content/folder/asset.png'
        asset.write_bytes(b'asset')
        self.api.raw_git('add', '.')
        self.api.raw_git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'asset')
        self.make_remote()
        self.live.synchronize()
        note = self.client.get('/api/editor/pages?path=folder/note.md').json()
        with patch.object(self.live, 'build', wraps=self.live.build) as build:
            result = self.batch([dict(note, body='Edited')], [
                {'type': 'move', 'source': 'folder', 'target_parent': ''},
                {'type': 'delete', 'source': 'folder'},
            ])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(result.json()['pages'], [{'original_path': 'folder/note.md', 'path': 'folder/note.md', 'deleted': True}])
        self.assertFalse(asset.parent.exists())
        self.assertEqual(result.json()['nodes'], [])
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertFalse((self.live.remote / 'content/folder').exists())
        self.assertFalse(self.live.pending())

    def test_create_edit_move_delete_one_batch(self):
        result = self.batch([{'slug': 'note', 'title': 'Note', 'body': 'New'}], [
            {'type': 'folder', 'slug': 'folder', 'title': 'Folder'},
            {'type': 'move', 'source': 'note.md', 'target_parent': 'folder'},
            {'type': 'delete', 'source': 'folder/note.md'},
        ])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['pages'], [{'original_path': 'note.md', 'path': 'folder/note.md', 'deleted': True}])
        self.assertEqual(result.json()['nodes'][0]['children'], [])

    def test_invalid_delete_rolls_back_entire_batch(self):
        for source in ('', '_index.md', '../wiki', '/tmp', 'missing', 'folder/_index.md'):
            with self.subTest(source=source):
                before = self.page()
                result = self.batch([dict(before, body='Unaccepted')], [
                    {'type': 'folder', 'slug': 'folder', 'title': 'Folder'},
                    {'type': 'delete', 'source': source},
                ])
                self.assertIn(result.status_code, (400, 404, 422), result.text)
                self.assertEqual(self.page(), before)
                self.assertEqual(self.client.get('/api/editor/tree').json()['nodes'], [])
                self.assertFalse(self.live.pending())

    def test_delete_stale_tree_preserves_page(self):
        self.assertEqual(self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Keep'}], []).status_code, 200)
        result = self.batch([], [{'type': 'delete', 'source': 'note.md'}], revision='0' * 40)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.get('/api/editor/pages?path=note.md').json()['body'], 'Keep')

    def test_delete_rejects_nested_asset_symlink(self):
        self.assertEqual(self.batch([], [{'type': 'folder', 'slug': 'folder', 'title': 'Folder'}]).status_code, 200)
        target = self.api.WORK / 'content/folder'
        (target / 'asset').symlink_to(self.root / 'outside')
        revision = self.api.content_revision()
        result = self.batch([], [{'type': 'delete', 'source': 'folder'}], revision=revision)
        self.assertIn(result.status_code, (400, 422), result.text)
        self.assertTrue(target.exists())

    def test_delete_unlinks_references_but_preserves_labels_and_code(self):
        self.assertEqual(self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Gone'}], []).status_code, 200)
        body = '[Ref]({{< relref "note.md#part" >}}) [Plain](/note/) [Absolute](' + self.api.ORIGIN + '/note/) ` [Code](/note/) `\n\n```md\n[Fenced](/note/)\n```\n'
        result = self.batch([dict(self.page(), body=body)], [{'type': 'delete', 'source': 'note.md'}])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.page()['body'], 'Ref Plain Absolute ` [Code](/note/) `\n\n```md\n[Fenced](/note/)\n```\n')

    def test_delete_unsupported_reference_rolls_back(self):
        self.assertEqual(self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Keep'}], []).status_code, 200)
        before = self.page()
        result = self.batch([dict(before, body='{{< relref "note.md" >}}')], [{'type': 'delete', 'source': 'note.md'}])
        self.assertEqual(result.status_code, 422, result.text)
        self.assertIn('unsupported reference in _index.md', result.json()['detail'])
        self.assertEqual(self.page(), before)
        self.assertEqual(self.client.get('/api/editor/pages?path=note.md').status_code, 200)

    def test_delete_folder_unlinks_alias_relative_and_asset_links(self):
        self.assertEqual(self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Gone'}, {'slug': 'other', 'title': 'Other', 'body': 'Keep'}], [
            {'type': 'folder', 'slug': 'folder', 'title': 'Folder'},
            {'type': 'move', 'source': 'note.md', 'target_parent': 'folder'},
        ]).status_code, 200)
        asset = self.api.WORK / 'content/folder/image.png'
        asset.write_bytes(b'image')
        self.api.raw_git('add', '.')
        self.api.raw_git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'asset')
        other = self.client.get('/api/editor/pages?path=other.md').json()
        result = self.batch([dict(other, body='[Alias](/note/) [Relative](../folder/note/) ![Picture](/folder/image.png) [Keep](https://example.com/folder/note/)')], [{'type': 'delete', 'source': 'folder'}])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/editor/pages?path=other.md').json()['body'], 'Alias Relative Picture [Keep](https://example.com/folder/note/)')

    def test_delete_folder_with_spaced_unicode_asset_name(self):
        self.assertEqual(self.batch([], [{'type': 'folder', 'slug': 'folder', 'title': 'Folder'}]).status_code, 200)
        asset = self.api.WORK / 'content/folder/my image.png'
        asset.write_bytes(b'image')
        (asset.parent / 'картинка.png').write_bytes(b'image')
        self.api.raw_git('add', '.')
        self.api.raw_git('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'assets')
        result = self.batch([dict(self.page(), body='![Picture](/folder/my%20image.png)')], [{'type': 'delete', 'source': 'folder'}])
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.page()['body'], 'Picture')
        self.assertFalse(asset.parent.exists())

    def test_live_fonts_use_font_mime_type(self):
        font = self.live.current / 'public' / 'test.woff2'
        font.write_bytes(b'font')
        response = self.client.get('/site/test.woff2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'font/woff2')
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_folder_rename_preserves_content_and_publishes_atomically(self):
        created = self.batch([{'slug': 'child', 'title': 'Child', 'body': 'Child body'}], [
            {'type': 'folder', 'slug': 'group', 'title': 'Group'},
            {'type': 'move', 'source': 'child.md', 'target_parent': 'group'},
        ])
        self.assertEqual(created.status_code, 200, created.text)
        folder = self.client.get('/api/editor/pages?path=group/_index.md').json()
        pending = len(self.live.pending())
        response = self.batch([dict(folder, body='Folder body')], [{'type': 'rename', 'source': 'group', 'title': ' Новое название '}])
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()['pages'][0]
        self.assertEqual(saved['title'], 'Новое название')
        self.assertEqual(saved['body'], 'Folder body')
        self.assertEqual(saved['path'], 'group/_index.md')
        self.assertEqual(saved['url'], self.api.ORIGIN + '/group/')
        self.assertEqual(self.client.get('/api/editor/pages?path=group/child.md').json()['body'], 'Child body')
        self.assertEqual(len(self.live.pending()), pending + 1)

    def test_create_move_rename_folder_in_one_batch(self):
        response = self.batch([], [
            {'type': 'folder', 'slug': 'group', 'title': 'Group'},
            {'type': 'folder', 'slug': 'parent', 'title': 'Parent'},
            {'type': 'rename', 'source': 'group', 'title': 'First'},
            {'type': 'move', 'source': 'group', 'target_parent': 'parent'},
            {'type': 'rename', 'source': 'parent/group', 'title': 'Final'},
        ])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/editor/pages?path=parent/group/_index.md').json()['title'], 'Final')
        self.assertEqual(len(self.live.pending()), 1)

    def test_invalid_folder_rename_rolls_back_page_edits(self):
        self.assertEqual(self.batch([{'slug': 'note', 'title': 'Note', 'body': 'Text'}], [{'type': 'folder', 'slug': 'group', 'title': 'Group'}]).status_code, 200)
        for source, title in [('note.md', 'Name'), ('', 'Name'), ('group', ''), ('group', 'a\nb'), ('group', 'a' * 201), ('../group', 'Name')]:
            before = self.page()
            pending = len(self.live.pending())
            response = self.batch([dict(before, body='Must not persist')], [{'type': 'rename', 'source': source, 'title': title}])
            self.assertIn(response.status_code, (400, 422), response.text)
            self.assertEqual(self.page(), before)
            self.assertEqual(len(self.live.pending()), pending)
