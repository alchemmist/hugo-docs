import base64
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import test_live


class UploadTest(unittest.TestCase):
    setUp = test_live.LiveTest.setUp
    tearDown = test_live.LiveTest.tearDown
    page = test_live.LiveTest.page

    def build(self, live, destination):
        test_live.LiveTest.build(self, live, destination)
        for path in (self.api.WORK / self.api.PREFIX).glob('upload-*'):
            shutil.copyfile(path, destination / 'public' / path.name)

    def stage(self):
        return self.client.post('/api/editor/uploads', json={'name': 'image.png', 'content': base64.b64encode(b'\x89PNG\r\n\x1a\nimage').decode()}, headers=self.headers)

    def test_staged_asset_is_private_until_atomic_publish(self):
        uploaded = self.stage()
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        record = uploaded.json()
        public = TestClient(self.api.app, base_url=self.api.ORIGIN)
        self.assertEqual(public.get(record['url']).status_code, 404)
        self.assertEqual(self.client.get(record['url']).status_code, 200)
        published = self.client.post('/api/editor/batch', json={'pages': [dict(self.page(), body='![Image](' + record['url'] + ')')], 'uploads': [record['id']]}, headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(public.get(record['url']).status_code, 200)
        self.assertTrue((self.api.WORK / self.api.PREFIX / record['id']).exists())

    def test_failed_build_keeps_upload_staged_and_old_site(self):
        record = self.stage().json()
        with patch.object(self.live, 'build', side_effect=self.api.HTTPException(422, 'Build failed')):
            response = self.client.post('/api/editor/batch', json={'uploads': [record['id']]}, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertFalse((self.api.WORK / self.api.PREFIX / record['id']).exists())
        self.assertEqual(self.client.get(record['url']).status_code, 200)
        self.assertEqual(TestClient(self.api.app, base_url=self.api.ORIGIN).get(record['url']).status_code, 404)

    def test_rejects_active_and_mismatched_uploads(self):
        for name in ('image.svg', 'index.html', 'fake.png'):
            response = self.client.post('/api/editor/uploads', json={'name': name, 'content': base64.b64encode(b'<script>alert(1)</script>').decode()}, headers=self.headers)
            self.assertEqual(response.status_code, 422)

    def test_editor_cannot_claim_another_editors_upload(self):
        record = self.stage().json()
        self.api.AUTH.create_user('another', 'another-password', 'editor')
        other = TestClient(self.api.app, base_url=self.api.ORIGIN)
        login = other.post('/api/auth/login', json={'username': 'another', 'password': 'another-password'}, headers={'Origin': self.api.ORIGIN}).json()
        response = other.post('/api/editor/batch', json={'uploads': [record['id']]}, headers={'Origin': self.api.ORIGIN, 'X-CSRF-Token': login['csrf_token']})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(other.get(record['url']).status_code, 403)
