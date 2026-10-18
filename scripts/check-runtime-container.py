import argparse
import http.cookiejar
import json
import re
import urllib.error
from urllib.parse import urljoin
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


def request(path, data=None, headers=None, method=None):
    headers = {'Origin': base, **(headers or {})}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    value = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers, method=method)
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
    run('run', '-d', '--name', name, '-p', f'127.0.0.1:{args.port}:8080', '-e', 'PUBLIC_ORIGIN=' + base + '/docs', '-e', 'WIKI_MCP_ENABLED=true', '-v', volume + ':/data', args.image)
    wait_for('/healthz')
    assert b'Your wiki' in request('/docs/')
    login = request('/docs/login').decode()
    assert '<dialog' not in login
    with opener.open(base + '/docs/admin', timeout=30) as response:
        assert '/docs/login' in response.url
    try:
        request('/docs/wiki-system.json')
    except urllib.error.HTTPError as error:
        assert error.code == 404
    else:
        raise AssertionError('System page manifest is public')
    assets = re.findall(r'(?:href|src)=["\']([^"\']+\.(?:css|js|woff2)(?:\?[^"\']*)?)["\']', login)
    assert assets
    fonts = set()
    for asset in assets:
        content = request(asset)
        if '.css' in asset:
            for font in re.findall(r'url\(["\']?([^"\')]+\.woff2(?:\?[^"\')]*)?)["\']?\)', content.decode()):
                fonts.add(urljoin(asset, font))
                assert request(urljoin(asset, font))
    assert fonts
    token = run('exec', name, 'cat', '/data/bootstrap-token')
    request('/docs/api/auth/bootstrap', {'username': 'admin', 'password': password, 'secret': token})
    request('/docs/api/auth/login', {'username': 'admin', 'password': password})
    admin = request('/docs/admin').decode()
    assert '<dialog' not in admin
    assert 'wiki-admin' in admin
    session = json.loads(request('/docs/api/editor/session'))
    assert session['writable']
    csrf = {'X-CSRF-Token': session['csrf_token']}
    assert json.loads(request('/docs/api/auth/preferences', {'theme': 'dark'}, csrf)) == {'theme': 'dark'}
    for path in ('/docs/', '/docs/admin'):
        themed = request(path).decode()
        assert re.search(r'<html\b[^>]*\bdata-theme="dark"', themed)
        styles = re.findall(r'href=["\']([^"\']*/theme\.[^"\']+\.css)["\']', themed)
        assert styles, path
        for style in styles:
            assert b'data-theme' in request(style)
    with urllib.request.urlopen(base + '/docs/', timeout=30) as response:
        anonymous = response.read().decode()
        assert re.search(r'<html\b[^>]*\bdata-theme="light"', anonymous)
    personal = json.loads(request('/docs/api/auth/tokens', {'name': 'Container acceptance', 'read_only': True}, csrf))

    protocol_version = '2025-11-25'

    def rpc(method, params):
        response = json.loads(request('/docs/mcp', {
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params,
        }, {
            'Authorization': 'Bearer ' + personal['token'],
            'Accept': 'application/json, text/event-stream',
            'MCP-Protocol-Version': protocol_version,
        }))
        assert 'error' not in response, response
        return response['result']

    initialized = rpc('initialize', {
        'protocolVersion': '2025-11-25', 'capabilities': {},
        'clientInfo': {'name': 'container-acceptance', 'version': '1'},
    })
    protocol_version = initialized['protocolVersion']
    request('/docs/mcp', {
        'jsonrpc': '2.0', 'method': 'notifications/initialized',
    }, {
        'Authorization': 'Bearer ' + personal['token'],
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': protocol_version,
    })
    assert 'tools' in initialized['capabilities']
    assert 'wiki_read_page' in {tool['name'] for tool in rpc('tools/list', {})['tools']}
    result = rpc('tools/call', {'name': 'wiki_read_page', 'arguments': {'path': '_index.md'}})
    assert not result.get('isError'), result
    assert result['structuredContent']['path'] == '_index.md'
    denied = rpc('tools/call', {'name': 'wiki_create_page', 'arguments': {
        'section': '', 'slug': 'forbidden', 'title': 'Forbidden', 'body': 'Denied',
    }})
    assert denied.get('isError'), denied
    assert '403' in denied['content'][0]['text'], denied
    request('/docs/api/auth/tokens/' + personal['id'], headers=csrf, method='DELETE')
    try:
        rpc('tools/list', {})
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError('Revoked MCP token was accepted')
    page = json.loads(request('/docs/api/editor/pages?path=_index.md'))
    page['body'] = 'Container publication acceptance.'
    request('/docs/api/editor/batch', {'pages': [page]}, {'X-CSRF-Token': session['csrf_token']})
    assert b'Container publication acceptance.' in request('/docs/')
    run('restart', name)
    wait_for('/docs/', b'Container publication acceptance.')
    for path in ('/docs/', '/docs/admin'):
        assert re.search(r'<html\b[^>]*\bdata-theme="dark"', request(path).decode())
    assert json.loads(request('/docs/api/auth/preferences', {'theme': 'light'}, csrf)) == {'theme': 'light'}
    assert re.search(r'<html\b[^>]*\bdata-theme="light"', request('/docs/').decode())
    print('Container acceptance passed: fresh volume, subpath health, public read, bootstrap/login, personal theme and anonymous isolation, MCP discovery/read/read-only/revocation, publication, restart persistence')
except Exception:
    subprocess.run([args.engine, 'logs', name], check=False)
    raise
finally:
    subprocess.run([args.engine, 'rm', '-f', name], check=False, stdout=subprocess.DEVNULL)
    subprocess.run([args.engine, 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
