import unittest
import test_app
from test_app import editor, run
from unittest.mock import patch


class StructureTest(unittest.TestCase):
    setUp = test_app.EditorTest.setUp
    tearDown = test_app.EditorTest.tearDown

    def seed_structure(self):
        root = self.seed / 'content'
        for name, title, weight in [('ai', 'AI', 20), ('start', 'Start', 10)]:
            (root / name).mkdir()
            (root / name / '_index.md').write_text(f'---\ntitle: {title}\nweight: {weight}\n---\n\nSection\n')
        (root / 'ai/chat.md').write_text('---\ntitle: Chat\nweight: 10\ncustom: keep\n---\n\nBody\n')
        (root / 'start/intro.md').write_text('---\ntitle: Intro\nweight: 10\n---\n\n[Chat]({{< relref "ai/chat.md#hello" >}})\n')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'structure')
        run(self.seed, 'push', 'origin', 'main')

    def tree(self):
        response = self.client.get('/api/editor/tree')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def move(self, source, parent='', before=None, revision=None):
        return self.client.post('/api/editor/move', headers=self.headers, json={'source': source, 'target_parent': parent, 'before': before, 'revision': revision or self.tree()['revision']})

    def test_create_empty_folder_and_order(self):
        self.seed_structure()
        tree = self.tree()
        self.assertEqual([node['id'] for node in tree['nodes']], ['start', 'ai'])
        response = self.client.post('/api/editor/folders', headers=self.headers, json={'parent': 'ai', 'slug': 'guides', 'title': 'Guides', 'revision': tree['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        page = editor.WORK / 'content/ai/guides/_index.md'
        self.assertTrue(page.is_file())
        self.assertIn('weight: 20', page.read_text())
        self.assertEqual(self.move('ai', before='start').status_code, 200)
        self.assertEqual([node['id'] for node in self.tree()['nodes']], ['ai', 'start'])
        self.assertEqual([node['weight'] for node in self.tree()['nodes']], [10, 20])

    def test_move_folder_preserves_body_aliases_and_references(self):
        self.seed_structure()
        response = self.move('ai', 'start')
        self.assertEqual(response.status_code, 200, response.text)
        root = editor.WORK / 'content'
        moved = (root / 'start/ai/chat.md').read_text()
        self.assertIn('custom: keep', moved)
        self.assertIn('/ai/chat/', moved)
        self.assertTrue(moved.endswith('Body\n'))
        self.assertIn('"/start/ai/chat.md#hello"', (root / 'start/intro.md').read_text())
        self.assertFalse((root / 'ai').exists())
        self.assertEqual(self.move('start/ai', '').status_code, 200)
        metadata, body = editor.parse((root / 'ai/chat.md').read_text())
        self.assertNotIn('/ai/chat/', metadata['aliases'])

    def test_cycle_conflict_collision_and_traversal(self):
        self.seed_structure()
        revision = self.tree()['revision']
        self.assertEqual(self.move('ai', 'ai').status_code, 422)
        self.assertEqual(self.move('../ai').status_code, 400)
        self.assertEqual(self.move('_index.md').status_code, 422)
        self.assertEqual(self.move('ai', before='start/intro.md').status_code, 422)
        self.assertEqual(self.move('ai', before='start').status_code, 200)
        self.assertEqual(self.move('ai', 'start', revision=revision).status_code, 409)
        response = self.client.post('/api/editor/folders', headers=self.headers, json={'parent': '', 'slug': 'start', 'title': 'Duplicate', 'revision': self.tree()['revision']})
        self.assertEqual(response.status_code, 409)

    def test_anchor_only_relref_stays_on_the_moved_page(self):
        self.seed_structure()
        page = self.seed / 'content/ai/chat.md'
        page.write_text('---\ntitle: Chat\n---\n\n[Self]({{< relref "#hello" >}})\n\n## Hello\n')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'anchor')
        run(self.seed, 'push', 'origin', 'main')
        self.assertEqual(self.move('ai/chat.md', 'start').status_code, 200)
        self.assertIn('relref "/start/chat.md#hello"', (editor.WORK / 'content/start/chat.md').read_text())

    def test_leaf_bundle_moves_assets_and_rejects_symlinks(self):
        self.seed_structure()
        bundle = self.seed / 'content/ai/demo'
        bundle.mkdir()
        (bundle / 'index.md').write_text('---\ntitle: Demo\n---\n\n![Image](image.png)\n')
        (bundle / 'image.png').write_bytes(b'asset')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'bundle')
        run(self.seed, 'push', 'origin', 'main')
        self.assertEqual(self.move('ai/demo', 'start').status_code, 200)
        self.assertEqual((editor.WORK / 'content/start/demo/image.png').read_bytes(), b'asset')
        (editor.WORK / 'content/start/demo/evil').symlink_to('/etc/passwd')
        with self.assertRaises(editor.HTTPException):
            editor.tree_nodes()

    def test_structure_push_race_retries_or_conflicts(self):
        self.seed_structure()
        revision = self.tree()['revision']
        original = editor.git
        raced = False
        def race(*args, **kwargs):
            nonlocal raced
            if args[0] == 'push' and not raced:
                raced = True
                (self.seed / 'unrelated.txt').write_text('other')
                run(self.seed, 'add', '.')
                run(self.seed, 'commit', '-m', 'unrelated')
                run(self.seed, 'push', 'origin', 'main')
            return original(*args, **kwargs)
        with patch.object(editor, 'git', race):
            response = self.move('ai', before='start', revision=revision)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((editor.WORK / 'unrelated.txt').exists())

    def test_move_rejects_alias_collision(self):
        self.seed_structure()
        page = self.seed / 'content/start/intro.md'
        page.write_text('---\ntitle: Intro\naliases: [/start/chat/]\n---\n\nBody\n')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'alias')
        run(self.seed, 'push', 'origin', 'main')
        response = self.move('ai/chat.md', 'start')
        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue((editor.WORK / 'content/ai/chat.md').exists())

    def test_structure_push_content_race_returns_conflict(self):
        self.seed_structure()
        revision = self.tree()['revision']
        original = editor.git
        raced = False
        def race(*args, **kwargs):
            nonlocal raced
            if args[0] == 'push' and not raced:
                raced = True
                page = self.seed / 'content/start/intro.md'
                page.write_text(page.read_text() + 'Concurrent edit\n')
                run(self.seed, 'add', '.')
                run(self.seed, 'commit', '-m', 'content changed')
                run(self.seed, 'push', 'origin', 'main')
            return original(*args, **kwargs)
        with patch.object(editor, 'git', race):
            response = self.move('ai', 'start', revision=revision)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertTrue((editor.WORK / 'content/ai/chat.md').exists())
        self.assertIn('Concurrent edit', (editor.WORK / 'content/start/intro.md').read_text())

    def test_page_creation_appends_and_conflicts_on_tree_revision(self):
        self.seed_structure()
        revision = self.tree()['revision']
        data = {'section': 'ai', 'slug': 'new-page', 'title': 'New', 'body': 'Body', 'tree_revision': revision}
        response = self.client.post('/api/editor/pages', headers=self.headers, json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('weight: 20', (editor.WORK / 'content/ai/new-page.md').read_text())
        data['slug'] = 'stale-page'
        response = self.client.post('/api/editor/pages', headers=self.headers, json=data)
        self.assertEqual(response.status_code, 409, response.text)
