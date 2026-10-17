import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


@unittest.skipUnless(shutil.which('hugo'), 'Hugo is required for the runtime smoke test')
class RuntimeSmokeTest(unittest.TestCase):
    def test_clean_start_publish_upload_and_restart_under_subpath(self):
        template = Path(__file__).parents[2] / 'runtime-site'
        if not (template / '_vendor').is_dir():
            self.skipTest('Vendor runtime-site Hugo modules before running smoke test')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(os.environ, {'WIKI_DATA_DIR': str(root), 'LIVE_TEMPLATE_DIR': str(template), 'PUBLIC_ORIGIN': 'http://localhost:8080/docs', 'LIVE_MODE': 'true', 'GIT_REPOSITORY': '', 'WIKI_CONFIG': str(root / 'wiki.yaml'), 'WIKI_BOOTSTRAP_SECRET_FILE': '', 'CONTENT_PREFIX': 'content', 'WORK_DIR': str(root / 'repository'), 'LIVE_STATE_DIR': str(root / 'live')}, clear=False):
                spec = importlib.util.spec_from_file_location('runtime_smoke_app', Path(__file__).parents[1] / 'app.py')
                api = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(api)
                with TestClient(api.app, base_url=api.ORIGIN + '/') as client:
                    self.assertEqual(client.get('/docs/').status_code, 200)
                    self.assertEqual(client.get('/healthz').status_code, 200)
                    competitor = type(api.LIVE)(api.LIVE.services, root=api.LIVE.root, template=api.LIVE.template)
                    with self.assertRaisesRegex(RuntimeError, 'exactly one writer'):
                        competitor.start()
                    self.assertEqual(client.get('/docs/api/editor/sync').status_code, 401)
                    origin = {'Origin': 'http://localhost:8080'}
                    response = client.post('/docs/api/auth/bootstrap', json={'secret': api.SETTINGS.bootstrap_secret, 'username': 'admin', 'password': 'testing-password'}, headers=origin)
                    self.assertEqual(response.status_code, 200, response.text)
                    login = client.post('/docs/api/auth/login', json={'username': 'admin', 'password': 'testing-password'}, headers=origin)
                    self.assertEqual(login.status_code, 200, login.text)
                    headers = dict(origin, **{'X-CSRF-Token': login.json()['csrf_token']})
                    encoded = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
                    uploaded = client.post('/docs/api/editor/uploads', json={'name': 'pixel.png', 'content': encoded}, headers=headers)
                    self.assertEqual(uploaded.status_code, 200, uploaded.text)
                    record = uploaded.json()
                    page = client.get('/docs/api/editor/pages', params={'path': '_index.md'}).json()
                    response = client.post('/docs/api/editor/batch', json={'pages': [dict(page, body='Unique published text\n\n![Pixel](' + record['url'] + ')\n')], 'uploads': [record['id']]}, headers=headers)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertIn('Unique published text', client.get('/docs/').text)
                    self.assertEqual(client.get(record['url']).content, base64.b64decode(encoded))
                    self.assertEqual(client.get('/docs/api/editor/sync').json()['pending'], 0)
                    state = json.loads((api.LIVE.current / 'state.json').read_text())
                    self.assertEqual(state['actor']['username'], 'admin')
                    self.assertEqual(len(state['patch_id']), 32)
                spec.loader.exec_module(api)
                with TestClient(api.app, base_url=api.ORIGIN + '/') as client:
                    self.assertIn('Unique published text', client.get('/docs/').text)
                    self.assertEqual(client.get(record['url']).status_code, 200)
