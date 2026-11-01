import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from auth import AuthStore
from oidc import configure_store,external_login
from fastapi import HTTPException

class OIDCAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{},clear=True);self.env.start();self.addCleanup(self.env.stop)
        self.store=AuthStore(Path(self.tmp.name)/'accounts.sqlite3')
        self.owner=self.store.create_user('admin','owner-password','admin')
        self.tim=self.store.create_user('antropophag','tim-password','editor')
        self.old,_=self.store.login('antropophag','tim-password')
        os.environ.update(WIKI_OIDC_ISSUER='https://idp.example/application/o/wiki/',WIKI_OIDC_LOCAL_OWNER_IDS=json.dumps([self.owner['id']]))
        configure_store(self.store)
    def test_only_owner_can_use_legacy_password_and_sessions(self):
        with self.assertRaises(HTTPException) as error:self.store.login('antropophag','tim-password')
        self.assertEqual(error.exception.status_code,401)
        self.assertIsNone(self.store.session(self.old))
        token,_=self.store.login('admin','owner-password');self.assertIsNotNone(self.store.session(token))
    def test_exact_subject_links_preserve_existing_identity(self):
        token=external_login(self.store,'issuer','tim-uuid','tim','editor',{'tim-uuid':self.tim['id']})
        self.assertEqual(self.store.session(token)['user']['id'],self.tim['id'])
        self.assertEqual(len(self.store.list_users()),2)
    def test_email_or_username_does_not_adopt_account(self):
        with self.assertRaises(HTTPException) as error:external_login(self.store,'issuer','attacker','admin','admin',{})
        self.assertEqual(error.exception.status_code,409)
    def test_cannot_link_two_subjects_to_one_account(self):
        external_login(self.store,'issuer','tim-uuid','tim','editor',{'tim-uuid':self.tim['id']})
        with self.assertRaises(HTTPException):external_login(self.store,'issuer','other','other','admin',{'other':self.tim['id']})
    def test_disabled_account_stays_disabled(self):
        self.store.update_user(self.tim['id'],disabled=True)
        with self.assertRaises(HTTPException):external_login(self.store,'issuer','tim','tim','editor',{'tim':self.tim['id']})
    def test_new_oidc_user_cannot_use_password(self):
        token=external_login(self.store,'issuer','new-user','new-reader','reader',{})
        self.assertEqual(self.store.session(token)['user']['role'],'reader')
        self.assertNotIn(self.store.session(token)['user']['id'],self.store.local_owners)
    def test_role_change_invalidates_previous_sessions(self):
        token=external_login(self.store,'issuer','tim','tim','editor',{'tim':self.tim['id']})
        external_login(self.store,'issuer','tim','tim','reader',{'tim':self.tim['id']})
        self.assertIsNone(self.store.session(token))
    def test_http_fallback_works_without_idp_and_local_tim_is_rejected(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth import install_auth
        pages=Path(self.tmp.name)/'pages';pages.mkdir()
        for page in ['login','admin']:
            for language in ['en','ru']:(pages/f'{page}.{language}.html').write_text('<html>fallback</html>')
        os.environ.update(WIKI_OIDC_CLIENT_ID='test-client',WIKI_OIDC_CLIENT_SECRET='test-only',
            WIKI_OIDC_SESSION_SECRET='test-state-key-not-production-1234567890',
            WIKI_OIDC_GROUP_ROLES='{"homelab-owner":"admin","homelab-observer":"reader"}')
        app=FastAPI();install_auth(app,origin='https://wiki.example',data_dir=self.tmp.name,system_pages_dir=pages)
        client=TestClient(app,base_url='https://wiki.example',follow_redirects=False)
        with patch('httpx.AsyncClient.request',side_effect=AssertionError('Fallback must not contact IdP')):
            self.assertEqual(client.get('/login').status_code,303)
            self.assertEqual(client.get('/login?local=1').status_code,200)
            headers={'Origin':'https://wiki.example'}
            self.assertEqual(client.post('/api/auth/login',headers=headers,json={'username':'antropophag','password':'tim-password'}).status_code,401)
            self.assertEqual(client.post('/api/auth/login',headers=headers,json={'username':'admin','password':'owner-password'}).status_code,200)
            self.assertEqual(client.get('/api/auth/oidc/callback?state=forged&code=forged').status_code,401)

    def test_owner_fallback_cannot_be_non_admin(self):
        os.environ['WIKI_OIDC_LOCAL_OWNER_IDS']=json.dumps([self.tim['id']])
        with self.assertRaises(RuntimeError):configure_store(self.store)
if __name__=='__main__':unittest.main()
