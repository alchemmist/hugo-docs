from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

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
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL
                );
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

    def public_user(self, row):
        return {key: row[key] for key in ('id', 'username', 'role', 'disabled')}

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
            return self.public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())

    def list_users(self):
        with self.connect() as db:
            return [self.public_user(row) for row in db.execute('SELECT * FROM users ORDER BY username')]

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
            return token, {'user': self.public_user(row), 'csrf_token': csrf}

    def digest(self, token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token):
        if not token or len(token) > 256:
            return None
        with self.connect() as db:
            row = db.execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id '
                             'WHERE sessions.token=? AND sessions.expires>? AND users.disabled=0',
                             (self.digest(token), time.time())).fetchone()
            return {'user': self.public_user(row), 'csrf_token': row['csrf']} if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (self.digest(token),))

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
            return self.public_user(db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone())


def install_auth(app, *, origin, data_dir, base_path='', public=True, bootstrap_secret='', session_seconds=28800):
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
        session = store.session(request.cookies.get('wiki_session'))
        request.state.auth = session
        auth_route = path.startswith('/api/auth/')
        editor_route = path == '/api/editor' or path.startswith('/api/editor/')
        admin_route = path == '/api/admin' or path.startswith('/api/admin/')
        allowed_public = path in ('/healthz', '/login', '/login/') or auth_route
        try:
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
                'writable': session['user']['role'] in ('editor', 'admin')}

    @app.get('/login', response_class=HTMLResponse)
    @app.get('/login/', response_class=HTMLResponse)
    async def login_page(request: Request):
        if request.state.auth:
            return RedirectResponse(prefix + '/', status_code=303)
        nonce = secrets.token_urlsafe(24)
        language = login_language(request.headers.get('accept-language', ''))
        page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in to wiki</title>
<style nonce="NONCE">body{font:16px system-ui;margin:10vh auto;padding:24px;max-width:360px}form{display:grid;gap:16px}label{display:grid;gap:6px}input,button{font:inherit;padding:10px}#error{color:#a00}[hidden]{display:none}</style>
<h1 id="title">Sign in to wiki</h1><form id="form"><label>Username<input name="username" autocomplete="username" required maxlength="254"></label><label>Password<input name="password" type="password" autocomplete="current-password" required minlength="8" maxlength="1024"></label><label id="bootstrap" hidden>Bootstrap token<input name="secret" type="password" autocomplete="off"></label><button id="submit">Sign in</button><p id="error" role="alert"></p></form>
<script nonce="NONCE">const base=BASE;const form=document.querySelector('form');const error=document.querySelector('#error');const submit=document.querySelector('#submit');let bootstrap=false;
async function request(path,body){const response=await fetch(base+path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'Request failed');return value;}
request('/api/auth/me').then(value=>{bootstrap=!!value.bootstrap_required;document.querySelector('#bootstrap').hidden=!bootstrap;if(bootstrap){document.querySelector('#title').textContent='Create administrator';submit.textContent='Create administrator';form.elements.password.autocomplete='new-password';}}).catch(e=>{error.textContent=e.message;});
form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;error.textContent='';const body=Object.fromEntries(new FormData(form));try{if(bootstrap)await request('/api/auth/bootstrap',body);await request('/api/auth/login',body);location.assign(base+'/');}catch(e){error.textContent=e.message;}finally{submit.disabled=false;}});</script></html>"""
        page = page.replace('NONCE', nonce).replace('BASE', json.dumps(prefix).replace('<', '\\u003c'))
        if language == 'ru':
            translations = {
                'Sign in to wiki': 'Вход в wiki',
                'Username': 'Логин',
                'Password': 'Пароль',
                'Bootstrap token': 'Секрет первоначальной настройки',
                'Sign in': 'Войти',
                'Create administrator': 'Создать администратора',
                'Request failed': 'Не удалось выполнить запрос',
            }
            page = page.replace('lang="en"', 'lang="ru"')
            for source, destination in translations.items():
                page = page.replace(source, destination)
            errors = {
                'Invalid credentials': 'Неверный логин или пароль',
                'Invalid bootstrap secret': 'Неверный секрет первоначальной настройки',
                'Administrator already initialized': 'Администратор уже создан',
                'Too many login attempts; retry later': 'Слишком много попыток входа. Попробуйте позже',
                'Password must contain 8 to 1024 characters': 'Пароль должен содержать от 8 до 1024 символов',
                'Invalid username': 'Некорректный логин',
                'Username already exists': 'Такой логин уже существует',
                'Invalid request origin': 'Недопустимый источник запроса',
            }
            page = page.replace("typeof value.detail==='string'?value.detail:",
                                "typeof value.detail==='string'?(" + json.dumps(errors, ensure_ascii=False) + "[value.detail]||value.detail):")
        return HTMLResponse(page, headers={
            'Cache-Control': 'no-store',
            'Content-Security-Policy': f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            'Referrer-Policy': 'no-referrer',
            'Content-Language': language,
            'Vary': 'Accept-Language',
        })

    @app.get('/api/editor/session')
    @app.get('/api/auth/me')
    async def current(request: Request):
        if not request.state.auth:
            return {'user': None, 'writable': False, 'csrf_token': None, 'csrf': None,
                    'bootstrap_required': not bool(store.list_users())}
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

    @app.post('/api/auth/password')
    async def password(request: Request):
        body = await payload(request)
        session = request.state.auth
        token, _ = store.login(session['user']['username'], body.get('current_password'))
        store.logout(token)
        store.validate('user', body.get('password'), 'reader')
        store.update_user(session['user']['id'], password=body['password'])
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
