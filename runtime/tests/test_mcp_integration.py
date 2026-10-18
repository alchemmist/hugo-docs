from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class MCPIntegrationTests(unittest.TestCase):
    @contextmanager
    def application(self, enabled=True, prefix=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / 'template'
            (template / 'content').mkdir(parents=True)
            (template / 'content/_index.md').write_text('---\ntitle: Home\n---\n\nInitial\n')
            with patch.dict(os.environ, WIKI_CONFIG=str(root / 'absent.yaml'), LIVE_MODE='true',
                            WIKI_MCP_ENABLED=str(enabled).lower(), GIT_REPOSITORY='',
                            WIKI_DATA_DIR=str(root / 'data'), PUBLIC_ORIGIN='https://wiki.example' + prefix,
                            CONTENT_PREFIX='content', LIVE_STATE_DIR=str(root / 'live'),
                            LIVE_TEMPLATE_DIR=str(template), WORK_DIR=str(root / 'work')):
                name = 'mcp_integration_application'
                spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / 'app.py')
                api = importlib.util.module_from_spec(spec)
                sys.modules[name] = api
                spec.loader.exec_module(api)
                def render(live, destination):
                    for source in (api.WORK / 'content').rglob('*.md'):
                        relative = source.relative_to(api.WORK / 'content')
                        page = relative.parent if relative.stem == '_index' else relative.with_suffix('')
                        output = destination / 'public' / page / 'index.html'
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_text(source.read_text())
                try:
                    with patch.object(type(api.LIVE), 'build', render):
                        with TestClient(api.app, base_url='https://wiki.example') as client:
                            yield api, client
                    self.assertIsNone(api.LIVE.writer_lock)
                finally:
                    sys.modules.pop(name, None)

    def token(self, api, client, role='editor', read_only=False, prefix=''):
        username = role + ('-readonly' if read_only else '')
        user = api.AUTH.create_user(username, 'integration-password', role)
        response = client.post(prefix + '/api/auth/login',
                               json={'username': username, 'password': 'integration-password'},
                               headers={'Origin': 'https://wiki.example'})
        self.assertEqual(response.status_code, 200, response.text)
        headers = {'Origin': 'https://wiki.example', 'X-CSRF-Token': response.json()['csrf_token']}
        response = client.post(prefix + '/api/auth/tokens', json={'name': 'Integration agent', 'read_only': read_only}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return user, response.json(), headers

    def rpc(self, client, token, method, params, prefix=''):
        response = client.post(prefix + '/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, headers={
            'Authorization': 'Bearer ' + token,
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': '2025-11-25',
        })
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertNotIn('error', payload, payload)
        return payload['result']

    def call(self, client, token, name, arguments=None, prefix='', error=None):
        result = self.rpc(client, token, 'tools/call', {'name': name, 'arguments': arguments or {}}, prefix)
        if error:
            self.assertTrue(result['isError'], result)
            self.assertIn(error, result['content'][0]['text'])
            return result
        self.assertFalse(result.get('isError'), result)
        return result['structuredContent']

    def test_full_lifecycle_publication_conflict_and_actor(self):
        with self.application() as (api, client):
            user, created, headers = self.token(api, client)
            token = created['token']
            initialized = self.rpc(client, token, 'initialize', {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'integration-agent', 'version': '1'},
            })
            self.assertIn('tools', initialized['capabilities'])
            self.assertEqual(len(self.rpc(client, token, 'tools/list', {})['tools']), 6)
            result = self.call(client, token, 'wiki_create_page', {
                'section': '', 'slug': 'agent-note', 'title': 'Agent note', 'body': 'Original body',
            })
            self.assertEqual(result['status'], 'published')
            self.assertIn('Original body', client.get('/agent-note/').text)
            state = json.loads((api.LIVE.current / 'state.json').read_text())
            self.assertEqual(state['actor'], user)
            self.assertEqual(state['commit'], result['commit'])
            note = self.call(client, token, 'wiki_read_page', {'path': 'agent-note.md'})
            updated = self.call(client, token, 'wiki_update_page', {
                **{key: note[key] for key in ('path', 'revision', 'title')}, 'body': 'Accepted update',
            })
            current = api.LIVE.current.resolve()
            self.call(client, token, 'wiki_update_page', {
                **{key: note[key] for key in ('path', 'revision', 'title')}, 'body': 'Stale overwrite',
            }, error='409')
            self.assertEqual(api.LIVE.current.resolve(), current)
            self.assertIn('Accepted update', client.get('/agent-note/').text)
            self.assertNotIn('Stale overwrite', client.get('/agent-note/').text)
            search = self.call(client, token, 'wiki_search', {'query': 'Accepted update'})
            self.assertEqual(search['results'][0]['path'], 'agent-note.md')
            tree = self.call(client, token, 'wiki_list_pages')
            self.call(client, token, 'wiki_delete_page', {'path': 'agent-note.md', 'tree_revision': tree['revision']})
            self.assertEqual(client.get('/agent-note/').status_code, 404)
            self.call(client, token, 'wiki_read_page', {'path': 'agent-note.md'}, error='404')
            self.assertNotEqual(updated['commit'], json.loads((api.LIVE.current / 'state.json').read_text())['commit'])
            self.assertEqual(client.delete('/api/auth/tokens/' + created['id'], headers=headers).status_code, 200)
            self.assertEqual(client.post('/mcp', headers={'Authorization': 'Bearer ' + token}).status_code, 401)

    def test_reader_readonly_cookie_and_invalid_token_cannot_publish(self):
        with self.application() as (api, client):
            for role, read_only in [('reader', False), ('admin', True)]:
                _, created, _ = self.token(api, client, role, read_only)
                current = api.LIVE.current.resolve()
                self.assertEqual(self.call(client, created['token'], 'wiki_read_page', {'path': '_index.md'})['title'], 'Home')
                self.call(client, created['token'], 'wiki_create_page', {
                    'section': '', 'slug': 'forbidden', 'title': 'Forbidden', 'body': 'Denied',
                }, error='403')
                self.assertEqual(api.LIVE.current.resolve(), current)
                self.assertFalse((api.WORK / 'content/forbidden.md').exists())
            self.assertEqual(client.post('/mcp').status_code, 401)
            self.assertEqual(client.post('/mcp', headers={'Authorization': 'Bearer invalid'}).status_code, 401)

    def test_render_failure_rolls_back_git_and_visible_content(self):
        with self.application() as (api, client):
            _, token, _ = self.token(api, client)
            note = self.call(client, token['token'], 'wiki_read_page', {'path': '_index.md'})
            current = api.LIVE.current.resolve()
            commit = api.raw_git('rev-parse', 'HEAD')
            with patch.object(api.LIVE, 'build', side_effect=api.HTTPException(422, 'Invalid document')):
                self.call(client, token['token'], 'wiki_update_page', {
                    **{key: note[key] for key in ('path', 'revision', 'title')}, 'body': 'Never published',
                }, error='422')
            self.assertEqual(api.raw_git('rev-parse', 'HEAD'), commit)
            self.assertEqual(api.LIVE.current.resolve(), current)
            self.assertEqual(self.call(client, token['token'], 'wiki_read_page', {'path': '_index.md'}), note)
            self.assertNotIn('Never published', client.get('/').text)

    def test_config_defaults_enable_override_and_invalid_values(self):
        from config import Settings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'wiki.yaml'
            with patch.dict(os.environ, {'WIKI_CONFIG': str(config), 'WIKI_DATA_DIR': str(root / 'data')}, clear=True):
                self.assertFalse(Settings.load().mcp_enabled)
                config.write_text('mcp:\n  enabled: true\n')
                self.assertTrue(Settings.load().mcp_enabled)
                with patch.dict(os.environ, WIKI_MCP_ENABLED='false'):
                    self.assertFalse(Settings.load().mcp_enabled)
                for invalid in ('true', '[]', 'null', '{enabled: "true"}', '{enabled: 1}'):
                    config.write_text('mcp: ' + invalid + '\n')
                    with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                        Settings.load()

    def test_feature_off_and_subpath(self):
        with self.application(enabled=False) as (api, client):
            self.assertIsNone(api.MCP)
            self.assertEqual(client.post('/mcp').status_code, 404)
            self.assertEqual(client.get('/api/auth/tokens').status_code, 404)
        with self.application(prefix='/docs') as (api, client):
            _, token, _ = self.token(api, client, prefix='/docs')
            page = self.call(client, token['token'], 'wiki_read_page', {'path': '_index.md'}, prefix='/docs')
            self.assertEqual(page['title'], 'Home')
            self.assertEqual(client.get('/docs/api/auth/me').json()['mcp_url'], 'https://wiki.example/docs/mcp')
            self.assertEqual(client.post('/mcp', headers={'Authorization': 'Bearer ' + token['token']}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
