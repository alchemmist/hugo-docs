import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import AuthStore, install_auth


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = AuthStore(Path(self.directory.name) / 'accounts.sqlite3')
        self.user = self.store.create_user('editor', 'long-password', 'editor')

    def test_plaintext_returned_once_and_ownership(self):
        token = self.store.create_token(self.user['id'], 'Pi', read_only=True)
        self.assertTrue(token['token'].startswith('wiki_'))
        self.assertEqual(self.store.token_session(token['token'])['user'], self.user)
        self.assertTrue(self.store.token_session(token['token'])['read_only'])
        listed = self.store.list_tokens(self.user['id'])
        self.assertEqual(listed, [{key: value for key, value in token.items() if key != 'token'}])
        with self.store.connect() as db:
            row = dict(db.execute('SELECT * FROM api_tokens').fetchone())
            self.assertNotIn(token['token'], row.values())
            self.assertEqual(row['token_hash'], self.store.digest(token['token']))
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0], '1')
        other = self.store.create_user('other', 'long-password')
        with self.assertRaises(HTTPException) as error:
            self.store.revoke_token(other['id'], token['id'])
        self.assertEqual(error.exception.status_code, 404)
        self.assertIsNotNone(self.store.token_session(token['token']))
        self.store.revoke_token(self.user['id'], token['id'])
        self.assertIsNone(self.store.token_session(token['token']))

    def test_expiry_and_current_permissions(self):
        token = self.store.create_token(self.user['id'], 'test', expires_days=1)
        with self.store.connect() as db:
            db.execute("UPDATE users SET role='reader' WHERE id=?", (self.user['id'],))
        self.assertEqual(self.store.token_session(token['token'])['user']['role'], 'reader')
        with patch('auth.time.time', return_value=time.time() + 86401):
            self.assertIsNone(self.store.token_session(token['token']))
            self.assertEqual(self.store.list_tokens(self.user['id']), [])
        with self.store.connect() as db:
            db.execute('UPDATE users SET disabled=1 WHERE id=?', (self.user['id'],))
        self.assertIsNone(self.store.token_session(token['token']))
        with self.assertRaises(HTTPException):
            self.store.create_token(self.user['id'], 'disabled')

    def test_account_updates_revoke_tokens(self):
        for change in ({'password': 'new-password'}, {'role': 'reader'}, {'disabled': True}):
            token = self.store.create_token(self.user['id'], 'test')
            self.store.update_user(self.user['id'], **change)
            self.assertIsNone(self.store.token_session(token['token']))

    def test_limits_and_validation(self):
        for kwargs in ({'name': ''}, {'name': 'x' * 101}, {'name': []},
                       {'expires_days': 0}, {'expires_days': 366}, {'expires_days': True},
                       {'read_only': 'false'}):
            with self.assertRaises(HTTPException):
                self.store.create_token(self.user['id'], **{'name': 'test', **kwargs})
        for index in range(50):
            self.store.create_token(self.user['id'], str(index))
        with self.assertRaises(HTTPException) as error:
            self.store.create_token(self.user['id'], 'overflow')
        self.assertEqual(error.exception.status_code, 409)
        for invalid in (None, '', 'wiki_bad', 'x' * 10000, 4):
            self.assertIsNone(self.store.token_session(invalid))

    def client(self, enabled=True, public=True, prefix=''):
        app = FastAPI()
        store = install_auth(app, origin='https://wiki.example' + prefix, data_dir=self.directory.name,
                             public=public, mcp_enabled=enabled)
        @app.api_route('/mcp', methods=['GET', 'POST', 'DELETE'])
        @app.api_route('/mcp/', methods=['GET', 'POST', 'DELETE'])
        async def mcp(request: Request):
            return request.state.auth
        @app.get('/secret')
        async def secret():
            return {'private': True}
        return TestClient(app, base_url='https://wiki.example', root_path=prefix), store

    def login(self, client):
        response = client.post('/api/auth/login', json={'username': 'editor', 'password': 'long-password'},
                               headers={'Origin': 'https://wiki.example'})
        self.assertEqual(response.status_code, 200)
        return {'Origin': 'https://wiki.example', 'X-CSRF-Token': response.json()['csrf_token']}

    def test_management_requires_cookie_csrf_origin(self):
        client, store = self.client()
        self.assertEqual(client.get('/api/auth/tokens').status_code, 401)
        headers = self.login(client)
        self.assertTrue(client.get('/api/auth/me').json()['mcp_enabled'])
        for bad_headers in ({}, {'Origin': 'https://evil.example', 'X-CSRF-Token': headers['X-CSRF-Token']},
                            {'Origin': 'https://wiki.example'}, {'X-CSRF-Token': headers['X-CSRF-Token']}):
            self.assertEqual(client.post('/api/auth/tokens', json={'name': 'Pi'}, headers=bad_headers).status_code, 403)
        created = client.post('/api/auth/tokens', json={'name': 'Pi'}, headers=headers)
        self.assertEqual(created.status_code, 200)
        token = created.json()
        self.assertNotIn('token', client.get('/api/auth/tokens').json()['tokens'][0])
        self.assertEqual(client.delete('/api/auth/tokens/' + token['id']).status_code, 403)
        self.assertEqual(client.delete('/api/auth/tokens/' + token['id'], headers=headers).status_code, 200)
        self.assertIsNone(store.token_session(token['token']))

    def test_mcp_bearer_only_and_origin(self):
        client, store = self.client(public=False)
        self.login(client)
        self.assertEqual(client.post('/mcp').status_code, 401)
        client.cookies.clear()
        token = store.create_token(self.user['id'], 'test', read_only=True)['token']
        headers = {'Authorization': 'Bearer ' + token}
        for path in ('/mcp', '/mcp/'):
            response = client.post(path, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['read_only'])
            self.assertEqual(response.json()['user']['role'], 'editor')
            self.assertEqual(client.post(path, headers={**headers, 'Origin': 'https://evil.example'}).status_code, 403)
            self.assertEqual(client.post(path, headers={**headers, 'Origin': 'https://wiki.example'}).status_code, 200)
        self.assertEqual(client.get('/secret', headers=headers).status_code, 401)
        self.assertEqual(client.get('/api/auth/tokens', headers=headers).status_code, 401)
        unauthorized = client.post('/mcp', headers={'Authorization': 'Bearer invalid'})
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(unauthorized.headers['www-authenticate'], 'Bearer')
        self.assertEqual(client.get('/mcp/extra', headers=headers).status_code, 401)

    def test_disabled_and_subpath(self):
        client, _ = self.client(enabled=False, public=False)
        for path in ('/mcp', '/mcp/', '/api/auth/tokens', '/api/auth/tokens/example'):
            self.assertEqual(client.get(path).status_code, 404)
            self.assertEqual(client.post(path).status_code, 404)
        session = client.get('/api/auth/me').json()
        self.assertFalse(session['mcp_enabled'])
        self.assertIsNone(session['mcp_url'])
        client, store = self.client(prefix='/docs')
        self.assertEqual(client.get('/api/auth/me').json()['mcp_url'], 'https://wiki.example/docs/mcp')
        token = store.create_token(self.user['id'], 'test')['token']
        self.assertEqual(client.post('/mcp', headers={'Authorization': 'Bearer ' + token}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
