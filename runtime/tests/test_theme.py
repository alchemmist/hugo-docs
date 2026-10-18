from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import AuthStore
from theme import apply_theme


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_existing_account_database_upgrades_without_credentials_or_session_changes(self):
        path = self.root / 'accounts.sqlite3'
        store = AuthStore(path)
        user = store.create_user('reader', 'long-password')
        other = store.create_user('other', 'long-password')
        first, session = store.login('reader', 'long-password')
        second, _ = store.login('reader', 'long-password')
        personal = store.create_token(user['id'], 'agent')
        with closing(sqlite3.connect(path)) as db:
            db.execute('DROP TABLE user_preferences')
            db.commit()
        store = AuthStore(path)
        self.assertEqual(store.session(first)['user']['theme'], 'light')
        store.set_theme(user['id'], 'dark')
        store = AuthStore(path)
        for token in (first, second):
            self.assertEqual(store.session(token)['user']['theme'], 'dark')
        self.assertEqual(store.session(first)['csrf_token'], session['csrf_token'])
        self.assertEqual(store.token_session(personal['token'])['user']['theme'], 'dark')
        self.assertEqual(store.login('reader', 'long-password')[1]['user']['theme'], 'dark')
        self.assertEqual(next(u for u in store.list_users() if u['id'] == other['id'])['theme'], 'light')
        for invalid in ('Dark', '', None, {}, True, 1):
            with self.assertRaises(HTTPException) as caught:
                store.set_theme(user['id'], invalid)
            self.assertEqual(caught.exception.status_code, 422)
        store.update_user(user['id'], disabled=True)
        with self.assertRaises(HTTPException) as caught:
            store.set_theme(user['id'], 'light')
        self.assertEqual(caught.exception.status_code, 404)

    def test_root_attribute_only_and_safe_value(self):
        source = '<!doctype html><!-- <html> --><html lang="en" data-theme="light"><body><code>data-theme="light"</code></body></html>'
        result = apply_theme(source, 'dark')
        self.assertIn('<html lang="en" data-theme="dark">', result)
        self.assertIn('<!-- <html> -->', result)
        self.assertIn('<code>data-theme="light"</code>', result)
        self.assertEqual(apply_theme('<html>hello</html>', '" onclick="bad'), '<html data-theme="light">hello</html>')

    def test_preferences_and_first_response_html_under_base_path(self):
        pages = self.root / 'pages'
        pages.mkdir()
        for page in ('login', 'admin'):
            for language in ('en', 'ru'):
                (pages / f'{page}.{language}.html').write_text('<html lang="en"><body>Account</body></html>')
        fingerprint = 'a' * 64
        font_url = f'/fonts/font.{fingerprint}.woff2'
        (pages / 'font.woff2').write_bytes(b'font')
        (pages / 'public-assets.json').write_text(json.dumps({font_url: 'font.woff2'}))
        with patch.dict(os.environ, {
            'WIKI_CONFIG': str(self.root / 'absent.yaml'), 'LIVE_MODE': 'true', 'WIKI_PUBLIC': 'true',
            'WIKI_SYSTEM_PAGES_DIR': str(pages), 'WIKI_DATA_DIR': str(self.root / 'data'),
            'PUBLIC_ORIGIN': 'https://wiki.example/docs', 'LIVE_STATE_DIR': str(self.root / 'live'),
            'WIKI_BOOTSTRAP_SECRET_FILE': str(self.root / 'bootstrap'), 'WIKI_MCP_ENABLED': 'true',
        }):
            spec = importlib.util.spec_from_file_location('theme_integration_app', Path(__file__).parents[1] / 'app.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        public = module.LIVE.current / 'public'
        public.mkdir(parents=True)
        (public / 'index.html').write_text('<html><body>Wiki</body></html>')
        module.LIVE.started = True
        reader = module.AUTH.create_user('reader', 'long-password')
        other = module.AUTH.create_user('other', 'long-password')
        client = TestClient(module.app, base_url='https://wiki.example', follow_redirects=False)
        self.addCleanup(client.close)
        origin = {'Origin': 'https://wiki.example'}
        endpoint = '/docs/api/auth/preferences'
        self.assertEqual(client.post(endpoint, json={'theme': 'dark'}, headers=origin).status_code, 401)
        token = module.AUTH.create_token(reader['id'], 'agent')['token']
        self.assertEqual(client.post(endpoint, json={'theme': 'dark'}, headers={**origin, 'Authorization': f'Bearer {token}'}).status_code, 401)
        for path in ('/docs/', '/docs/site/', '/docs/login'):
            response = client.get(path)
            self.assertIn('data-theme="light"', response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertIn('Cookie', response.headers['vary'])
        response = client.post('/docs/api/auth/login', json={'username': 'reader', 'password': 'long-password'}, headers=origin)
        headers = {**origin, 'X-CSRF-Token': response.json()['csrf_token']}
        self.assertEqual(client.post(endpoint, json={'theme': 'dark'}, headers=origin).status_code, 403)
        self.assertEqual(client.post(endpoint, json={'theme': 'dark'}, headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(client.post(endpoint, json={'theme': 'dark', 'user_id': other['id']}, headers=headers).status_code, 422)
        self.assertEqual(client.post(endpoint, json={'theme': 'dark'}, headers=headers).json(), {'theme': 'dark'})
        self.assertEqual(client.get('/docs/api/auth/me').json()['user']['theme'], 'dark')
        self.assertEqual(client.get('/docs/api/admin/users').status_code, 403)
        for path in ('/docs/', '/docs/site/', '/docs/admin'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn('data-theme="dark"', response.text)
            self.assertIn('Cookie', response.headers['vary'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(client.get('/docs/login').headers['location'], '/docs/admin')
        font = client.get('/docs' + font_url)
        self.assertEqual(font.content, b'font')
        self.assertIn('immutable', font.headers['cache-control'])
        self.assertNotIn('vary', font.headers)
        client.post('/docs/api/auth/logout', headers=headers)
        self.assertIn('data-theme="light"', client.get('/docs/').text)
        self.assertIn('data-theme="light"', client.get('/docs/login').text)
        self.assertEqual(client.get('/docs/admin').status_code, 303)
