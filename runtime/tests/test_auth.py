import importlib.util
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import AuthStore, SystemPages, install_auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = AuthStore(Path(self.directory.name) / 'auth.sqlite3')
        self.pages = Path(self.directory.name) / 'system-pages'
        self.pages.mkdir()
        for page in ('login', 'admin'):
            for language in ('en', 'ru'):
                (self.pages / f'{page}.{language}.html').write_text(
                    f'<html lang="{language}"><div id="wiki-{page}" data-base-path="__WIKI_BASE_PATH__"></div></html>')
        (self.pages / 'theme.css').write_text('body{font-family:CourierCyr}')
        (self.pages / 'font.woff2').write_bytes(b'font')
        (self.pages / 'public-assets.json').write_text(json.dumps({
            '/theme.css': 'theme.css', '/fonts/font.woff2': 'font.woff2',
        }))

    def test_persistent_sessions_and_revocation(self):
        admin = self.store.create_user('admin', 'long-password', 'admin', bootstrap=True)
        token, session = self.store.login('ADMIN', 'long-password')
        reopened = AuthStore(self.store.path)
        self.assertEqual(reopened.session(token)['user']['id'], admin['id'])
        reopened.update_user(admin['id'], password='new-password')
        self.assertIsNone(self.store.session(token))
        with self.assertRaises(HTTPException):
            self.store.login('admin', 'long-password')
        self.assertNotIn('password', session['user'])
        with self.store.connect() as db:
            row = db.execute('SELECT password FROM users').fetchone()
            self.assertTrue(row[0].startswith('$argon2id$'))
            self.assertFalse(db.execute('SELECT 1 FROM sessions WHERE token=?', (token,)).fetchone())

    def test_one_time_bootstrap_and_last_admin(self):
        admin = self.store.create_user('admin', 'long-password', 'admin', bootstrap=True)
        for changes in ({'disabled': True}, {'role': 'reader'}):
            with self.assertRaises(HTTPException) as caught:
                self.store.update_user(admin['id'], **changes)
            self.assertEqual(caught.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.store.create_user('second', 'long-password', 'admin', bootstrap=True)
        self.store.create_user('second', 'long-password', 'admin')
        token, _ = self.store.login('admin', 'long-password')
        self.store.update_user(admin['id'], disabled=True)
        self.assertIsNone(self.store.session(token))
        with self.assertRaises(HTTPException):
            self.store.login('admin', 'long-password')

    def client(self, public=True):
        app = FastAPI()
        store = install_auth(app, origin='https://wiki.example', data_dir=self.directory.name,
                             public=public, bootstrap_secret='bootstrap-test', system_pages_dir=self.pages)
        @app.get('/api/editor/tree')
        def tree():
            return {'ok': True}
        @app.post('/api/editor/batch')
        def batch():
            return {'ok': True}
        @app.get('/private-page')
        def page():
            return {'ok': True}
        @app.get('/healthz')
        def health():
            return {'ok': True}
        return TestClient(app, base_url='https://wiki.example'), store

    def test_http_roles_csrf_origin_bootstrap_and_logout(self):
        client, store = self.client()
        self.assertFalse(client.get('/api/editor/session').json()['writable'])
        self.assertEqual(client.get('/api/editor/tree').status_code, 401)
        headers = {'Origin': 'https://wiki.example'}
        body = {'username': 'admin', 'password': 'long-password', 'secret': 'bootstrap-test'}
        self.assertEqual(client.post('/api/auth/bootstrap', json=body).status_code, 403)
        self.assertEqual(client.post('/api/auth/bootstrap', json=body, headers=headers).status_code, 200)
        self.assertEqual(client.post('/api/auth/bootstrap', json=body, headers=headers).status_code, 409)
        response = client.post('/api/auth/login', json=body, headers=headers)
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie']
        for flag in ('HttpOnly', 'Secure', 'SameSite=strict'):
            self.assertIn(flag, cookie)
        headers['X-CSRF-Token'] = response.json()['csrf_token']
        self.assertEqual(client.post('/api/editor/batch', headers={'Origin': 'https://wiki.example'}).status_code, 403)
        self.assertEqual(client.post('/api/editor/batch', headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(client.post('/api/editor/batch', headers=headers).status_code, 200)
        self.assertEqual(client.get('/api/admin/users').status_code, 200)
        store.create_user('reader', 'long-password', 'reader')
        self.assertEqual(client.post('/api/auth/logout', headers=headers).status_code, 200)
        self.assertIsNone(client.get('/api/auth/me').json()['user'])
        reader = client.post('/api/auth/login', json={'username': 'reader', 'password': 'long-password'}, headers=headers)
        self.assertFalse(reader.json()['writable'])
        self.assertEqual(client.get('/api/editor/tree').status_code, 403)
        self.assertEqual(client.get('/api/admin/users').status_code, 403)

    def test_private_pages_are_protected_and_reader_can_read(self):
        client, store = self.client(public=False)
        self.assertEqual(client.get('/private-page').status_code, 401)
        self.assertEqual(client.get('/healthz').status_code, 200)
        store.create_user('reader', 'long-password', 'reader')
        client.post('/api/auth/login', json={'username': 'reader', 'password': 'long-password'},
                    headers={'Origin': 'https://wiki.example'})
        self.assertEqual(client.get('/private-page').status_code, 200)
        self.assertEqual(client.get('/api/editor/tree').status_code, 403)

    def test_generated_bootstrap_secret_and_subpath_cookie(self):
        secret_path = Path(self.directory.name) / 'bootstrap-token'
        app = FastAPI()
        with patch.dict('os.environ', {'WIKI_BOOTSTRAP_SECRET_FILE': str(secret_path)}):
            store = install_auth(app, origin='https://wiki.example/docs/', data_dir=self.directory.name)
        self.assertEqual(secret_path.stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len(secret_path.read_text()), 32)
        store.create_user('admin', 'long-password', 'admin')
        client = TestClient(app, base_url='https://wiki.example')
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'long-password'},
                               headers={'Origin': 'https://wiki.example'})
        self.assertIn('Path=/docs/', response.headers['set-cookie'])

    def test_malformed_and_oversized_auth_requests(self):
        client, _ = self.client()
        headers = {'Origin': 'https://wiki.example'}
        for body in ('[]', 'null', 'no-json'):
            self.assertEqual(client.post('/api/auth/login', content=body, headers=headers).status_code, 422)
        self.assertEqual(client.post('/api/auth/login', content='x' * 17000, headers=headers).status_code, 413)

    def test_real_app_private_routes_subpath_and_login(self):
        with patch.dict(os.environ, {
            'WIKI_CONFIG': str(Path(self.directory.name) / 'absent.yaml'),
            'LIVE_MODE': 'false', 'WIKI_PUBLIC': 'false',
            'WIKI_SYSTEM_PAGES_DIR': str(self.pages),
            'WIKI_DATA_DIR': self.directory.name, 'PUBLIC_ORIGIN': 'https://wiki.example/docs',
            'WIKI_BOOTSTRAP_SECRET_FILE': str(Path(self.directory.name) / 'token'),
        }):
            spec = importlib.util.spec_from_file_location('auth_integration_app', Path(__file__).parents[1] / 'app.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        client = TestClient(module.app, base_url='https://wiki.example', follow_redirects=False)
        for path in ('/', '/site/', '/search.json', '/upload-secret.png', '/api/editor/tree'):
            self.assertEqual(client.get('/docs' + path).status_code, 401, path)
        redirect = client.get('/docs/site/', headers={'Accept': 'text/html'})
        self.assertEqual(redirect.status_code, 303)
        self.assertEqual(redirect.headers['location'], '/docs/login')
        page = client.get('/docs/login')
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('frame-ancestors', page.headers['content-security-policy'])
        self.assertIn('data-base-path="/docs"', page.text)
        self.assertEqual(client.get('/api/editor/session').status_code, 404)
        module.AUTH.create_user('reader', 'long-password', 'reader')
        response = client.post('/docs/api/auth/login', json={'username': 'reader', 'password': 'long-password'},
                               headers={'Origin': 'https://wiki.example'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(client.get('/docs/api/editor/tree').status_code, 403)
        self.assertEqual(client.get('/docs/api/admin/users').status_code, 403)
        self.assertEqual(client.get('/docs/site/').status_code, 404)
        self.assertEqual(client.get('/docs/api/editor/session').json()['user']['role'], 'reader')

    def test_login_page_localization(self):
        client, _ = self.client()
        for preference, language, label in (
            ('ru-RU,ru;q=0.9,en;q=0.8', 'ru', 'Создать администратора'),
            ('ru;q=0.4,en;q=0.9', 'en', 'Create administrator'),
            ('fr', 'en', 'Create administrator'),
            ('ru;q=0,en;q=0.1', 'en', 'Create administrator'),
        ):
            response = client.get('/login', headers={'Accept-Language': preference})
            self.assertEqual(response.headers['content-language'], language)
            self.assertIn(f'lang="{language}"', response.text)
            self.assertIn('Accept-Language', response.headers['vary'])

    def test_site_language_overrides_browser_preference(self):
        client, store = self.client()
        for language, preference in (('ru', 'en-US'), ('en', 'ru-RU')):
            (self.pages / 'language.txt').write_text(language)
            response = client.get('/login', headers={'Accept-Language': preference})
            self.assertEqual(response.headers['content-language'], language)
            self.assertIn(f'lang="{language}"', response.text)
        store.create_user('reader', 'long-password', 'reader')
        client.post('/api/auth/login', json={'username': 'reader', 'password': 'long-password'},
                    headers={'Origin': 'https://wiki.example'})
        (self.pages / 'language.txt').write_text('ru')
        response = client.get('/admin', headers={'Accept-Language': 'en'})
        self.assertEqual(response.headers['content-language'], 'ru')

    def test_account_page_requires_login_for_public_wiki_and_allows_reader(self):
        client, store = self.client()
        for path in ('/admin', '/admin/'):
            response = client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/login')
        store.create_user('reader', 'long-password', 'reader')
        client.post('/api/auth/login', json={'username': 'reader', 'password': 'long-password'},
                    headers={'Origin': 'https://wiki.example'})
        response = client.get('/admin')
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="wiki-admin"', response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(client.get('/api/admin/users').status_code, 403)
        self.assertEqual(client.get('/login', follow_redirects=False).headers['location'], '/admin')

    def test_private_login_assets_are_allowlisted_without_content_exposure(self):
        client, _ = self.client(public=False)
        for path in ('/theme.css', '/fonts/font.woff2'):
            response = client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        for path in ('/private.css', '/_wiki/private.css', '/fonts/private.woff2', '/search.json', '/upload-secret.png', '/private-page'):
            self.assertEqual(client.get(path).status_code, 401, path)
        response = client.get('/login')
        self.assertIn("font-src 'self'", response.headers['content-security-policy'])
        self.assertNotIn('system-ui', response.text)

    def test_selected_icon_is_public_and_unhashed_resource_is_not_cached(self):
        (self.pages / 'icon.svg').write_text('<svg></svg>')
        fingerprint = 'a' * 64
        (self.pages / 'public-assets.json').write_text(json.dumps({
            '/images/icon.svg': 'icon.svg', f'/fonts/font.{fingerprint}.woff2': 'font.woff2',
        }))
        client, _ = self.client(public=False)
        response = client.get('/images/icon.svg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'<svg></svg>')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(client.get('/images/private.png').status_code, 401)
        response = client.get(f'/fonts/font.{fingerprint}.woff2')
        self.assertIn('immutable', response.headers['cache-control'])

    def test_system_pages_follow_current_publication(self):
        current = Path(self.directory.name) / 'current'
        current.symlink_to(self.pages, target_is_directory=True)
        pages = SystemPages(current)
        self.assertIn('wiki-login', pages.render('login', 'en', '').body.decode())
        replacement = Path(self.directory.name) / 'replacement'
        replacement.mkdir()
        (replacement / 'login.en.html').write_text('<html>updated</html>')
        (replacement / 'public-assets.json').write_text('{}')
        current.unlink()
        current.symlink_to(replacement, target_is_directory=True)
        self.assertEqual(pages.render('login', 'en', '').body.decode(), '<html data-theme="light">updated</html>')
        self.assertEqual(pages.assets, {})

    def test_invalid_system_asset_manifest_cannot_expose_content(self):
        for relative in ('../auth.sqlite3', '/etc/passwd', 'login.en.html'):
            (self.pages / 'public-assets.json').write_text(json.dumps({'/_wiki/secret': relative}))
            with self.assertRaises(ValueError):
                SystemPages(self.pages).assets

    def test_self_password_requires_old_password_and_admin_reset_revokes(self):
        client, store = self.client()
        admin = store.create_user('admin', 'long-password', 'admin')
        reader = store.create_user('reader', 'reader-password', 'reader')
        reader_token, _ = store.login('reader', 'reader-password')
        headers = {'Origin': 'https://wiki.example'}
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'long-password'}, headers=headers)
        headers['X-CSRF-Token'] = response.json()['csrf_token']
        for old in ('wrong-password', None):
            result = client.post('/api/auth/password', json={'current_password': old, 'password': 'new-password'}, headers=headers)
            self.assertEqual(result.status_code, 401)
            self.assertEqual(client.get('/api/auth/me').json()['user']['id'], admin['id'])
        result = client.post('/api/admin/users/' + reader['id'] + '/password', json={'password': 'reset-password'}, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(store.session(reader_token))
        store.login('reader', 'reset-password')
        result = client.post('/api/auth/password', json={'current_password': 'long-password', 'password': 'new-password'}, headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(client.get('/api/auth/me').json()['user'])
        store.login('admin', 'new-password')

    def test_expiration_and_role_changes_revoke(self):
        user = self.store.create_user('user', 'long-password', 'editor')
        token, _ = self.store.login('user', 'long-password')
        self.store.update_user(user['id'], role='reader')
        self.assertIsNone(self.store.session(token))
        token, _ = self.store.login('user', 'long-password')
        with self.store.connect() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertIsNone(self.store.session(token))


if __name__ == '__main__':
    unittest.main()
