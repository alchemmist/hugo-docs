import argparse
import http.cookiejar
import json
import secrets
import subprocess
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--engine', default='docker')
parser.add_argument('--image', default='wiki:test')
parser.add_argument('--port', type=int, default=18881)
args = parser.parse_args()
password = secrets.token_urlsafe(24)
name = 'hugo-docs-smoke-' + secrets.token_hex(4)
volume = name + '-data'
base = f'http://127.0.0.1:{args.port}'


def run(*arguments):
    return subprocess.check_output([args.engine, *arguments], text=True).strip()


opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(path, data=None, headers=None):
    headers = {'Origin': base, **(headers or {})}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    value = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with opener.open(value, timeout=30) as response:
        return response.read()


def wait_for(path, expected=None):
    for attempt in range(90):
        try:
            body = request(path)
            if expected is None or expected in body:
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError(f'Container did not serve expected content at {path}')


run('volume', 'create', volume)
try:
    run('run', '-d', '--name', name, '-p', f'127.0.0.1:{args.port}:8080', '-e', 'PUBLIC_ORIGIN=' + base + '/docs', '-v', volume + ':/data', args.image)
    wait_for('/healthz')
    assert b'Your wiki' in request('/docs/')
    token = run('exec', name, 'cat', '/data/bootstrap-token')
    request('/docs/api/auth/bootstrap', {'username': 'admin', 'password': password, 'secret': token})
    request('/docs/api/auth/login', {'username': 'admin', 'password': password})
    session = json.loads(request('/docs/api/editor/session'))
    assert session['writable']
    page = json.loads(request('/docs/api/editor/pages?path=_index.md'))
    page['body'] = 'Container publication acceptance.'
    request('/docs/api/editor/batch', {'pages': [page]}, {'X-CSRF-Token': session['csrf_token']})
    assert b'Container publication acceptance.' in request('/docs/')
    run('restart', name)
    wait_for('/docs/', b'Container publication acceptance.')
    print('Container acceptance passed: fresh volume, subpath health, public read, bootstrap/login, publication, restart persistence')
except Exception:
    subprocess.run([args.engine, 'logs', name], check=False)
    raise
finally:
    subprocess.run([args.engine, 'rm', '-f', name], check=False, stdout=subprocess.DEVNULL)
    subprocess.run([args.engine, 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
