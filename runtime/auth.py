from contextlib import contextmanager
import hashlib
import hmac
import html
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from theme import apply_theme

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

ROLES = frozenset(('reader', 'editor', 'admin'))
PASSWORD_HASHER = PasswordHasher()


def login_language(header):
    choices = []
    for index, entry in enumerate(header[:4096].split(',')):
        parts = entry.strip().lower().split(';')
        language = parts[0].split('-')[0]
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.strip().startswith('q='):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0
        if language in ('en', 'ru') and 0 < quality <= 1:
            choices.append((quality, -index, language))
    return max(choices)[2] if choices else 'en'


class SystemPages:
    def __init__(self, directory):
        self.directory = Path(directory)

    @property
    def assets(self):
        snapshot = SystemPages(self.directory.resolve())
        manifest = snapshot.directory / 'public-assets.json'
        assets = {}
        if manifest.is_file():
            entries = json.loads(manifest.read_text())
            if not isinstance(entries, dict):
                raise ValueError('Invalid system assets manifest')
            for url, relative in entries.items():
                if not isinstance(url, str) or not url.startswith('/') or '?' in url or '#' in url:
                    raise ValueError('Invalid system asset URL')
                target = snapshot.file(relative)
                if target.suffix.lower() not in ('.css', '.js', '.woff2', '.woff', '.ttf', '.otf', '.svg', '.png', '.ico'):
                    raise ValueError('Unsupported public system asset')
                assets[url] = target
        return assets

    def file(self, relative):
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError('Invalid system page path')
        target = (self.directory / relative).resolve()
        if not target.is_relative_to(self.directory.resolve()) or not target.is_file():
            raise ValueError('Missing or unsafe system page file')
        return target

    def language(self, header):
        try:
            language = self.file('language.txt').read_text().strip()
        except ValueError:
            language = None
        return language if language in ('en', 'ru') else login_language(header)

    def render(self, page, language, prefix, theme='light'):
        try:
            source = self.file(f'{page}.{language}.html').read_text()
        except ValueError as error:
            raise HTTPException(503, 'System pages are unavailable') from error
        nonce = secrets.token_urlsafe(24)
        body = source.replace('__WIKI_BASE_PATH__', html.escape(prefix, quote=True)).replace('__WIKI_NONCE__', nonce)
        return HTMLResponse(apply_theme(body, theme), headers={
            'Cache-Control': 'no-store',
            'Content-Security-Policy': f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'nonce-{nonce}'; font-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff',
            'Content-Language': language,
            'Vary': 'Accept-Language, Cookie',
        })


class AuthStore:
    def __init__(self, path, session_seconds=28800):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.session_seconds = session_seconds
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password TEXT NOT NULL, role TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    theme TEXT NOT NULL CHECK(theme IN ('light', 'dark'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL,
                    read_only INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS api_tokens_user ON api_tokens(user_id);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1');
            ''')
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
            if version != '1':
                raise RuntimeError('Unsupported account database version')
        os.chmod(self.path, 0o600)
        self.dummy_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def validate(self, username, password, role):
        if not isinstance(username, str) or not username.strip() or len(username) > 254:
            raise HTTPException(422, 'Invalid username')
        if not isinstance(password, str) or not 8 <= len(password) <= 1024:
            raise HTTPException(422, 'Password must contain 8 to 1024 characters')
        if not isinstance(role, str) or role not in ROLES:
            raise HTTPException(422, 'Invalid role')

    def public_user(self, row, db=None):
        if db is None:
            with self.connect() as connection:
                return self.public_user(row, connection)
        preference = db.execute('SELECT theme FROM user_preferences WHERE user_id=?', (row['id'],)).fetchone()
        return {**{key: row[key] for key in ('id', 'username', 'role', 'disabled')},
                'theme': preference['theme'] if preference else 'light'}

    def set_theme(self, user_id, theme):
        if not isinstance(theme, str) or theme not in ('light', 'dark'):
            raise HTTPException(422, 'Invalid theme')
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0', (user_id,)).fetchone():
                raise HTTPException(404, 'Active user not found')
            db.execute('INSERT INTO user_preferences (user_id, theme) VALUES (?, ?) '
                       'ON CONFLICT(user_id) DO UPDATE SET theme=excluded.theme', (user_id, theme))
        return {'theme': theme}

    def create_user(self, username, password, role='reader', bootstrap=False):
        self.validate(username, password, role)
        password_hash = PASSWORD_HASHER.hash(password)
        user_id = secrets.token_hex(16)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if bootstrap and db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
                raise HTTPException(409, 'Administrator already initialized')
            try:
                db.execute('INSERT INTO users VALUES (?, ?, ?, ?, 0)',
                           (user_id, username.strip(), password_hash, role))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, 'Username already exists') from error
            return self.public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone(), db)

    def list_users(self):
        with self.connect() as db:
            return [self.public_user(row, db) for row in db.execute('SELECT * FROM users ORDER BY username')]

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
            raise HTTPException(401, 'Invalid credentials')
        with self.lock, self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE username=? COLLATE NOCASE', (username.strip(),)).fetchone()
            try:
                valid = PASSWORD_HASHER.verify(row['password'] if row else self.dummy_hash, password)
            except VerificationError:
                valid = False
            if not valid or not row or row['disabled']:
                raise HTTPException(401, 'Invalid credentials')
            if PASSWORD_HASHER.check_needs_rehash(row['password']):
                db.execute('UPDATE users SET password=? WHERE id=?', (PASSWORD_HASHER.hash(password), row['id']))
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?)',
                       (self.digest(token), row['id'], csrf, time.time() + self.session_seconds))
            return token, {'user': self.public_user(row, db), 'csrf_token': csrf}

    def digest(self, token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token):
        if not token or len(token) > 256:
            return None
        with self.connect() as db:
            row = db.execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id '
                             'WHERE sessions.token=? AND sessions.expires>? AND users.disabled=0',
                             (self.digest(token), time.time())).fetchone()
            return {'user': self.public_user(row, db), 'csrf_token': row['csrf']} if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (self.digest(token),))

    def token_metadata(self, row):
        return {**{key: row[key] for key in ('id', 'name', 'created_at', 'expires_at')},
                'read_only': bool(row['read_only'])}

    def create_token(self, user_id, name, expires_days=90, read_only=False):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise HTTPException(422, 'Token name must contain 1 to 100 characters')
        if type(expires_days) is not int or not 1 <= expires_days <= 365:
            raise HTTPException(422, 'Token expiry must be between 1 and 365 days')
        if type(read_only) is not bool:
            raise HTTPException(422, 'Read only must be a boolean')
        now = time.time()
        token = 'wiki_' + secrets.token_urlsafe(48)
        token_id = secrets.token_hex(16)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM users WHERE id=? AND disabled=0', (user_id,)).fetchone():
                raise HTTPException(404, 'Active user not found')
            db.execute('DELETE FROM api_tokens WHERE user_id=? AND expires_at<=?', (user_id, now))
            if db.execute('SELECT COUNT(*) FROM api_tokens WHERE user_id=?', (user_id,)).fetchone()[0] >= 50:
                raise HTTPException(409, 'Maximum of 50 active tokens reached')
            db.execute('INSERT INTO api_tokens VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (token_id, self.digest(token), user_id, name.strip(), now, now + expires_days * 86400, read_only))
            row = db.execute('SELECT * FROM api_tokens WHERE id=?', (token_id,)).fetchone()
            return {**self.token_metadata(row), 'token': token}

    def list_tokens(self, user_id):
        with self.connect() as db:
            return [self.token_metadata(row) for row in db.execute(
                'SELECT * FROM api_tokens WHERE user_id=? AND expires_at>? ORDER BY created_at DESC',
                (user_id, time.time()))]

    def revoke_token(self, user_id, token_id):
        with self.connect() as db:
            if not db.execute('DELETE FROM api_tokens WHERE id=? AND user_id=?', (token_id, user_id)).rowcount:
                raise HTTPException(404, 'Token not found')

    def token_session(self, raw):
        if not isinstance(raw, str) or not re.fullmatch(r'wiki_[A-Za-z0-9_-]{64}', raw):
            return None
        with self.connect() as db:
            row = db.execute(
                'SELECT users.*, api_tokens.id AS token_id, api_tokens.read_only FROM api_tokens '
                'JOIN users ON users.id=api_tokens.user_id '
                'WHERE api_tokens.token_hash=? AND api_tokens.expires_at>? AND users.disabled=0',
                (self.digest(raw), time.time())).fetchone()
            return {'user': self.public_user(row, db), 'token_id': row['token_id'],
                    'read_only': bool(row['read_only'])} if row else None

    def update_user(self, user_id, *, role=None, disabled=None, password=None):
        if role is not None and (not isinstance(role, str) or role not in ROLES):
            raise HTTPException(422, 'Invalid role')
        if disabled is not None and type(disabled) is not bool:
            raise HTTPException(422, 'Disabled must be a boolean')
        if password is not None:
            self.validate('user', password, 'reader')
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'User not found')
            next_role = row['role'] if role is None else role
            next_disabled = row['disabled'] if disabled is None else disabled
            if row['role'] == 'admin' and not row['disabled'] and (next_role != 'admin' or next_disabled):
                count = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0]
                if count <= 1:
                    raise HTTPException(409, 'Cannot disable or demote the last administrator')
            db.execute('UPDATE users SET role=?, disabled=?, password=? WHERE id=?',
                       (next_role, next_disabled, PASSWORD_HASHER.hash(password) if password is not None else row['password'], user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM api_tokens WHERE user_id=?', (user_id,))
            return self.public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone(), db)


def install_auth(app, *, origin, data_dir, base_path='', public=True, bootstrap_secret='', session_seconds=28800, system_pages_dir=None, mcp_enabled=False):
    pages = SystemPages(system_pages_dir or os.getenv('WIKI_SYSTEM_PAGES_DIR', '/opt/wiki-system'))
    parsed = urlsplit(origin)
    allowed_origin = parsed.scheme + '://' + parsed.netloc
    prefix = '/' + (base_path or parsed.path).strip('/') if (base_path or parsed.path).strip('/') else ''
    cookie_path = prefix + '/'
    secure = parsed.scheme == 'https'
    store = AuthStore(Path(data_dir) / 'accounts.sqlite3', session_seconds)
    if not bootstrap_secret and os.getenv('WIKI_BOOTSTRAP_SECRET_FILE'):
        secret_path = Path(os.environ['WIKI_BOOTSTRAP_SECRET_FILE'])
        if not secret_path.exists():
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, 'w') as handle:
                    handle.write(secrets.token_urlsafe(32))
                    handle.flush()
                    os.fsync(handle.fileno())
        bootstrap_secret = secret_path.read_text().strip()
    attempts = {}
    attempts_lock = threading.Lock()

    async def payload(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, 'Request too large')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, 'Invalid JSON body')
        if not isinstance(value, dict):
            raise HTTPException(422, 'Expected an object')
        return value

    def require_origin(request):
        if request.headers.get('origin') != allowed_origin:
            raise HTTPException(403, 'Invalid request origin')

    def throttle(request):
        key = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        with attempts_lock:
            for expired in [item for item, values in attempts.items() if values[-1] < now - 60]:
                del attempts[expired]
            values = [value for value in attempts.get(key, []) if value > now - 60]
            if len(values) >= 10:
                raise HTTPException(429, 'Too many login attempts; retry later')
            attempts[key] = [*values, now]

    @app.middleware('http')
    async def authorize(request, call_next):
        path = request.url.path
        if prefix and (path == prefix or path.startswith(prefix + '/')):
            path = path[len(prefix):] or '/'
        if path in ('/mcp', '/mcp/'):
            if not mcp_enabled:
                return JSONResponse({'detail': 'Not found'}, status_code=404)
            if 'origin' in request.headers and request.headers['origin'] != allowed_origin:
                return JSONResponse({'detail': 'Invalid request origin'}, status_code=403)
            authorization = request.headers.get('authorization', '')
            scheme, _, raw = authorization.partition(' ')
            token_auth = store.token_session(raw) if scheme.lower() == 'bearer' else None
            if not token_auth:
                return JSONResponse({'detail': 'Valid bearer token required'}, status_code=401,
                                    headers={'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store'})
            request.state.auth = token_auth
            response = await call_next(request)
            response.headers['Cache-Control'] = 'no-store'
            return response
        token_route = path == '/api/auth/tokens' or path.startswith('/api/auth/tokens/')
        if token_route and not mcp_enabled:
            return JSONResponse({'detail': 'Not found'}, status_code=404)
        asset = pages.assets.get(path) if Path(path).suffix.lower() in ('.css', '.js', '.woff', '.woff2', '.ttf', '.otf', '.svg', '.png', '.ico') else None
        if asset is not None and request.method in ('GET', 'HEAD'):
            cache = 'public, max-age=31536000, immutable' if re.search(r'[.-][a-f0-9]{32,128}\.', path) else 'no-store'
            return FileResponse(asset, headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': cache})
        session = store.session(request.cookies.get('wiki_session'))
        request.state.auth = session
        if path in ('/admin', '/admin/') and not session:
            return RedirectResponse(prefix + '/login', status_code=303, headers={'Cache-Control': 'no-store'})
        auth_route = path.startswith('/api/auth/')
        editor_route = path == '/api/editor' or path.startswith('/api/editor/')
        admin_route = path == '/api/admin' or path.startswith('/api/admin/')
        allowed_public = path in ('/healthz', '/login', '/login/') or auth_route
        try:
            if (token_route or path == '/api/auth/preferences') and not session:
                raise HTTPException(401, 'Sign in required')
            if ((editor_route and path != '/api/editor/session') or admin_route or (not public and not allowed_public and path != '/api/editor/session')) and not session:
                raise HTTPException(401, 'Sign in required')
            if editor_route and path != '/api/editor/session' and session['user']['role'] not in ('editor', 'admin'):
                raise HTTPException(403, 'Editor role required')
            if admin_route and session['user']['role'] != 'admin':
                raise HTTPException(403, 'Administrator role required')
            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                require_origin(request)
                if path not in ('/api/auth/login', '/api/auth/bootstrap'):
                    csrf = request.headers.get('x-csrf-token', '')
                    if not session or not hmac.compare_digest(csrf.encode(), session['csrf_token'].encode()):
                        raise HTTPException(403, 'Invalid CSRF token')
        except HTTPException as error:
            if error.status_code == 401 and not public and request.method in ('GET', 'HEAD') and not path.startswith('/api/') and 'text/html' in request.headers.get('accept', ''):
                return RedirectResponse(prefix + '/login', status_code=303, headers={'Cache-Control': 'no-store'})
            return JSONResponse({'detail': error.detail}, status_code=error.status_code,
                                headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        if auth_route or editor_route or admin_route or not public:
            response.headers['Cache-Control'] = 'no-store'
        return response

    def session_response(session):
        return {**session, 'csrf': session['csrf_token'],
                'writable': session['user']['role'] in ('editor', 'admin'),
                'mcp_enabled': mcp_enabled, 'mcp_url': allowed_origin + prefix + '/mcp' if mcp_enabled else None}

    @app.get('/login', response_class=HTMLResponse)
    @app.get('/login/', response_class=HTMLResponse)
    async def login_page(request: Request):
        if request.state.auth:
            return RedirectResponse(prefix + '/admin', status_code=303, headers={'Cache-Control': 'no-store'})
        language = pages.language(request.headers.get('accept-language', ''))
        return pages.render('login', language, prefix)

    @app.get('/admin', response_class=HTMLResponse)
    @app.get('/admin/', response_class=HTMLResponse)
    async def admin_page(request: Request):
        language = pages.language(request.headers.get('accept-language', ''))
        return pages.render('admin', language, prefix, request.state.auth['user']['theme'])

    @app.get('/api/editor/session')
    @app.get('/api/auth/me')
    async def current(request: Request):
        if not request.state.auth:
            return {'user': None, 'writable': False, 'csrf_token': None, 'csrf': None,
                    'bootstrap_required': not bool(store.list_users()),
                    'mcp_enabled': mcp_enabled, 'mcp_url': allowed_origin + prefix + '/mcp' if mcp_enabled else None}
        return session_response(request.state.auth)

    @app.post('/api/auth/login')
    async def login(request: Request):
        throttle(request)
        body = await payload(request)
        token, session = store.login(body.get('username'), body.get('password'))
        response = JSONResponse(session_response(session))
        response.set_cookie('wiki_session', token, max_age=session_seconds, httponly=True,
                            secure=secure, samesite='strict', path=cookie_path)
        return response

    @app.post('/api/auth/bootstrap')
    async def bootstrap(request: Request):
        throttle(request)
        body = await payload(request)
        supplied = body.get('secret', '')
        if not bootstrap_secret or not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), bootstrap_secret.encode()):
            raise HTTPException(403, 'Invalid bootstrap secret')
        return store.create_user(body.get('username'), body.get('password'), 'admin', bootstrap=True)

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        store.logout(request.cookies.get('wiki_session', ''))
        response = JSONResponse({'ok': True})
        response.delete_cookie('wiki_session', path=cookie_path, secure=secure, httponly=True, samesite='strict')
        return response

    @app.post('/api/auth/preferences')
    async def preferences(request: Request):
        body = await payload(request)
        if set(body) != {'theme'}:
            raise HTTPException(422, 'Expected only theme')
        return store.set_theme(request.state.auth['user']['id'], body['theme'])

    @app.post('/api/auth/password')
    async def password(request: Request):
        body = await payload(request)
        session = request.state.auth
        token, _ = store.login(session['user']['username'], body.get('current_password'))
        store.logout(token)
        store.validate('user', body.get('password'), 'reader')
        store.update_user(session['user']['id'], password=body['password'])
        return {'ok': True}

    def token_user(request):
        if not mcp_enabled:
            raise HTTPException(404, 'Not found')
        if not request.state.auth or 'csrf_token' not in request.state.auth:
            raise HTTPException(401, 'Sign in required')
        return request.state.auth['user']['id']

    @app.get('/api/auth/tokens')
    async def tokens(request: Request):
        return {'tokens': store.list_tokens(token_user(request))}

    @app.post('/api/auth/tokens')
    async def create_personal_token(request: Request):
        user_id = token_user(request)
        body = await payload(request)
        return store.create_token(user_id, body.get('name'), body.get('expires_days', 90), body.get('read_only', False))

    @app.delete('/api/auth/tokens/{token_id}')
    async def revoke_personal_token(token_id: str, request: Request):
        store.revoke_token(token_user(request), token_id)
        return {'ok': True}

    @app.get('/api/admin/users')
    async def users():
        return {'users': store.list_users()}

    @app.post('/api/admin/users')
    async def create(request: Request):
        body = await payload(request)
        return store.create_user(body.get('username'), body.get('password'), body.get('role', 'reader'))

    @app.patch('/api/admin/users/{user_id}')
    async def update(user_id: str, request: Request):
        body = await payload(request)
        return store.update_user(user_id, role=body.get('role'), disabled=body.get('disabled'))

    @app.post('/api/admin/users/{user_id}/password')
    async def reset(user_id: str, request: Request):
        body = await payload(request)
        store.validate('user', body.get('password'), 'reader')
        return store.update_user(user_id, password=body['password'])

    return store
