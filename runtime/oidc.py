"""Optional native OIDC. Authlib validates code/PKCE, nonce and signed ID tokens.

Local account adoption is explicit issuer+subject -> user ID, never email/name.
When enabled, legacy passwords and pre-migration sessions are owner-only.
"""
import json
import os
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse


def configure_store(store):
    store.oidc_enabled = bool(os.getenv('WIKI_OIDC_ISSUER'))
    store.local_owners = set(json.loads(os.getenv('WIKI_OIDC_LOCAL_OWNER_IDS', '[]')))
    if not store.oidc_enabled:
        return
    if not store.local_owners:
        raise RuntimeError('OIDC requires explicit local emergency owner IDs')
    with store.connect() as db:
        for user_id in store.local_owners:
            row = db.execute('SELECT role,disabled FROM users WHERE id=?', (user_id,)).fetchone()
            if not row or row['role'] != 'admin' or row['disabled']:
                raise RuntimeError('Emergency owner must be an existing active administrator')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS oidc_accounts (
                issuer TEXT NOT NULL, subject TEXT NOT NULL,
                user_id TEXT NOT NULL UNIQUE REFERENCES users(id),
                PRIMARY KEY (issuer,subject)
            );
            CREATE TABLE IF NOT EXISTS oidc_sessions (
                token TEXT PRIMARY KEY REFERENCES sessions(token) ON DELETE CASCADE
            );
        ''')


def external_login(store, issuer, subject, username, role, links):
    from auth import PASSWORD_HASHER
    if not subject or not isinstance(subject, str) or len(subject) > 512:
        raise HTTPException(403, 'Invalid identity subject')
    if role not in ('reader', 'editor', 'admin'):
        raise HTTPException(403, 'No admitted role')
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        binding = db.execute('SELECT user_id FROM oidc_accounts WHERE issuer=? AND subject=?', (issuer,subject)).fetchone()
        user_id = binding['user_id'] if binding else links.get(subject)
        if binding and subject in links and links[subject] != user_id:
            raise HTTPException(409, 'Reviewed identity mapping differs')
        if not user_id:
            store.validate(username, secrets.token_urlsafe(32), role)
            if db.execute('SELECT 1 FROM users WHERE username=? COLLATE NOCASE', (username,)).fetchone():
                raise HTTPException(409, 'Account exists; explicit identity linking required')
            user_id = secrets.token_hex(16)
            db.execute('INSERT INTO users VALUES (?, ?, ?, ?, 0)',
                       (user_id, username, PASSWORD_HASHER.hash(secrets.token_urlsafe(48)), role))
        row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
        if not row or row['disabled']:
            raise HTTPException(403, 'Account is not active')
        # No unreviewed subject may acquire the local owner's identity.
        if user_id in store.local_owners and links.get(subject) != user_id:
            raise HTTPException(403, 'Owner requires an explicit subject mapping')
        if not binding:
            other = db.execute('SELECT 1 FROM oidc_accounts WHERE user_id=?', (user_id,)).fetchone()
            if other:
                raise HTTPException(409, 'Account already linked to another subject')
            db.execute('INSERT INTO oidc_accounts VALUES (?,?,?)', (issuer,subject,user_id))
        if row['role'] != role:
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM api_tokens WHERE user_id=?', (user_id,))
            db.execute('UPDATE users SET role=? WHERE id=?', (role,user_id))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        digest = store.digest(token)
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (digest,user_id,csrf,time.time()+store.session_seconds))
        db.execute('INSERT INTO oidc_sessions VALUES (?)', (digest,))
        return token


def install_oidc(app, store, origin, prefix, cookie_path, session_seconds):
    from authlib.integrations.starlette_client import OAuth
    from starlette.middleware.sessions import SessionMiddleware
    issuer = os.environ['WIKI_OIDC_ISSUER']
    if not issuer.startswith('https://') or '?' in issuer or '#' in issuer:
        raise RuntimeError('OIDC issuer must be a fixed HTTPS URL')
    secret = os.environ['WIKI_OIDC_SESSION_SECRET']
    if len(secret) < 32:
        raise RuntimeError('OIDC state signing key is too short')
    groups = json.loads(os.environ['WIKI_OIDC_GROUP_ROLES'])
    links = json.loads(os.getenv('WIKI_OIDC_LINKS', '{}'))
    overrides = json.loads(os.getenv('WIKI_OIDC_SUBJECT_ROLES', '{}'))
    if any(r not in ('reader','editor','admin') for r in [*groups.values(),*overrides.values()]):
        raise RuntimeError('Unsupported OIDC role')
    oauth = OAuth()
    client = oauth.register('wiki', client_id=os.environ['WIKI_OIDC_CLIENT_ID'],
        client_secret=os.environ['WIKI_OIDC_CLIENT_SECRET'],
        server_metadata_url=issuer.rstrip('/')+'/.well-known/openid-configuration',
        client_kwargs={'scope':'openid profile email','code_challenge_method':'S256'})
    app.add_middleware(SessionMiddleware, secret_key=secret, session_cookie='wiki_oidc_state',
        max_age=600, same_site='lax', https_only=True, path=cookie_path)

    @app.get('/api/auth/oidc/login')
    async def start(request: Request):
        response = await client.authorize_redirect(request, origin+prefix+'/api/auth/oidc/callback')
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/auth/oidc/callback')
    async def callback(request: Request):
        try:
            token = await client.authorize_access_token(request)
            claims = token.get('userinfo')
            # Authlib validates signature, exp, aud and nonce; still pin issuer.
            if not claims or claims.get('iss') != issuer or not claims.get('sub'):
                raise ValueError('Invalid ID token')
            membership = claims.get('groups', [])
            if not isinstance(membership, list) or not all(isinstance(g,str) for g in membership):
                raise ValueError('Invalid groups claim')
            admitted = [groups[g] for g in membership if g in groups]
            if not admitted:
                raise HTTPException(403, 'Application membership required')
            role = max(admitted, key=lambda r: ('reader','editor','admin').index(r))
            role = overrides.get(claims['sub'],role)
            raw = external_login(store,issuer,claims['sub'],claims.get('preferred_username',''),role,links)
        except HTTPException:
            raise
        except Exception:
            # Do not expose codes, JWTs, credentials or provider exception URLs.
            raise HTTPException(401,'OIDC verification failed') from None
        request.session.clear()
        response = RedirectResponse(prefix+'/admin',status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
        response.set_cookie('wiki_session',raw,max_age=session_seconds,httponly=True,
                            secure=True,samesite='lax',path=cookie_path)
        return response
