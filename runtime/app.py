import hmac
import json
import os
import posixpath
from pathlib import Path
import re
import shutil
import subprocess
import threading
import urllib.request

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from markdown_it import MarkdownIt

from audit import actor_context
from content_security import validate_content
from uploads import UploadStore
from config import Settings
from frontmatter import parse as parse_frontmatter, dump as dump_frontmatter, FrontMatterError

SETTINGS = Settings.load()
ORIGIN = SETTINGS.public_url
REPO = SETTINGS.repository
WORK = SETTINGS.work_dir
BRANCH = SETTINGS.branch
PREFIX = SETTINGS.content_prefix
LOCK = threading.RLock()
MAX_BODY = 262144
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, dependencies=[Depends(actor_context)])
LIVE_MODE = SETTINGS.live
LIVE = None
UPLOADS = UploadStore(SETTINGS.data_dir / 'uploads', ORIGIN)


@app.exception_handler(RuntimeError)
async def unavailable(request, error):
    return JSONResponse({'detail': 'Repository operation unavailable; retry shortly'}, status_code=503)


def git(*args, cwd=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    key = os.getenv('GIT_SSH_KEY')
    if key:
        import shlex
        hosts = os.environ['GIT_KNOWN_HOSTS']
        env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o IdentitiesOnly=yes -i ' + shlex.quote(key) + ' -o UserKnownHostsFile=' + shlex.quote(hosts)
    try:
        result = subprocess.run(['git', *args], cwd=cwd or WORK, env=env, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Git operation timed out') from error
    if result.returncode:
        raise RuntimeError('Git operation failed: ' + args[0])
    return result.stdout.strip()


raw_git = git


def sync():
    if LIVE_MODE:
        LIVE.initialize()
        return
    if not (WORK / '.git').exists():
        WORK.parent.mkdir(parents=True, exist_ok=True)
        git('clone', '--branch', BRANCH, '--single-branch', '--', REPO, str(WORK), cwd=WORK.parent)
    git('fetch', 'origin', BRANCH)
    git('reset', '--hard', 'origin/' + BRANCH)


def checked_path(value, section=False):
    if not isinstance(value, str) or '\\' in value or '\x00' in value:
        raise HTTPException(400, 'Invalid content path')
    parts = [] if value == '' and section else value.split('/')
    if any(p in ('', '.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', p) for p in parts):
        raise HTTPException(400, 'Invalid content path')
    if not section and not value.endswith('.md'):
        raise HTTPException(400, 'Only Markdown pages are supported')
    root = WORK / PREFIX
    for node in [WORK, *[WORK.joinpath(*Path(PREFIX).parts[:i]) for i in range(1, len(Path(PREFIX).parts) + 1)], root, *[root.joinpath(*parts[:i]) for i in range(1, len(parts) + 1)]]:
        if node.is_symlink():
            raise HTTPException(400, 'Symbolic links are not supported')
    return root / value


def parse(text):
    try:
        return parse_frontmatter(text)
    except FrontMatterError as error:
        raise HTTPException(422, str(error)) from error


def page_url(path):
    path = path.removesuffix('.md')
    if path.endswith('_index'):
        path = path[:-6]
    elif path.endswith('/index'):
        path = path[:-5]
    return ORIGIN + '/' + path.strip('/') + ('/' if path.strip('/') else '')


def read_page(path):
    target = checked_path(path)
    if not target.is_file():
        raise HTTPException(404, 'Page not found')
    raw = target.read_bytes()
    try:
        data, body = parse(raw.decode('utf-8'))
    except UnicodeError:
        raise HTTPException(422, 'Page must be UTF-8')
    revision = git('hash-object', '--', str(target))
    return {'path': path, 'title': str(data.get('title', '')), 'body': body, 'revision': revision}


def fields(data):
    title, body = data.get('title'), data.get('body')
    if not isinstance(title, str) or not title.strip() or len(title) > 300 or '\n' in title:
        raise HTTPException(422, 'Title must contain 1–300 characters on one line')
    if not isinstance(body, str) or len(body.encode('utf-8')) > MAX_BODY or '\x00' in body:
        raise HTTPException(422, 'Markdown body must be at most 256 KiB')
    validate_content(body)
    return title.strip(), body


def save(data, create=False):
    title, body = fields(data)
    with LOCK:
        sync()
        if create and data.get('tree_revision') and data['tree_revision'] != content_revision():
            raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
        if create:
            section, slug = data.get('section', ''), data.get('slug', '')
            parent = checked_path(section, section=True)
            if not parent.is_dir() or not (parent / '_index.md').is_file():
                raise HTTPException(422, 'Choose an existing section')
            if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
                raise HTTPException(422, 'Slug must use lowercase letters, digits and hyphens')
            if slug == 'index' or (parent / slug).exists():
                raise HTTPException(409, 'This URL is reserved or already belongs to a section')
            path = '/'.join(filter(None, [section, slug + '.md']))
        else:
            path = data.get('path')
            if not isinstance(data.get('revision'), str):
                raise HTTPException(422, 'Base revision is required')
        for attempt in range(3):
            target = checked_path(path)
            if create:
                if target.exists():
                    raise HTTPException(409, 'A page with this slug already exists')
                if data.get('tree_revision') and data['tree_revision'] != content_revision():
                    raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
                assert_available_url(page_url(path))
                siblings = tree_nodes(section)
                renumber(siblings)
                metadata = {'weight': (len(siblings) + 1) * 10}
            else:
                existing = read_page(path)
                if not hmac.compare_digest(existing['revision'], data['revision']):
                    raise HTTPException(409, 'Page changed since it was opened; reload before saving')
                metadata, unused = parse(target.read_text())
            metadata['title'] = title
            write_markdown(target, metadata, body)
            git('add', '--', PREFIX if create else PREFIX + '/' + path)
            if not git('diff', '--cached', '--name-only'):
                return {'commit': git('rev-parse', 'HEAD'), 'path': path, 'url': page_url(path), 'revision': git('hash-object', '--', str(target))}
            base_commit = git('rev-parse', 'HEAD')
            revision = git('hash-object', '--', str(target))
            git('-c', 'user.name=' + SETTINGS.git_author, '-c', 'user.email=' + SETTINGS.git_email, 'commit', '-m', ('add' if create else 'update') + ' wiki page ' + path.lower())
            commit = git('rev-parse', 'HEAD')
            try:
                if not LIVE_MODE:
                    git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
                return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': git('hash-object', '--', str(target))}
            except RuntimeError as error:
                sync()
                remote_commit = git('rev-parse', 'HEAD')
                if remote_commit == commit:
                    return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': revision}
                try:
                    git('merge-base', '--is-ancestor', commit, remote_commit)
                    return {'commit': commit, 'path': path, 'url': page_url(path), 'revision': revision}
                except RuntimeError:
                    pass
                if remote_commit == base_commit:
                    raise RuntimeError('Repository push unavailable') from error
        raise HTTPException(409, 'Concurrent repository update; retry saving')


def write_markdown(target, metadata, body):
    target.write_text(dump_frontmatter(metadata, body), encoding='utf-8')


def content_revision():
    return git('rev-parse', 'HEAD:' + PREFIX)


def node_metadata(node):
    path = node['id']
    if node['kind'] == 'folder':
        path += '/_index.md'
    elif not path.endswith('.md'):
        path += '/index.md'
    return checked_path(path)


def document_url(path, metadata):
    custom = metadata.get('url')
    if custom:
        if not isinstance(custom, str) or not custom.startswith('/') or custom.startswith('//'):
            raise HTTPException(422, 'Unsupported page URL')
        return ORIGIN + custom
    if metadata.get('slug'):
        parent = str(Path(path).parent)
        if Path(path).name == 'index.md':
            parent = str(Path(parent).parent)
        return ORIGIN + '/' + '/'.join(filter(None, [parent if parent != '.' else '', str(metadata['slug'])])) + '/'
    return page_url(path)


def tree_nodes(parent=''):
    directory = checked_path(parent, section=True)
    result = []
    for item in directory.iterdir():
        if item.name.startswith('.'):
            raise HTTPException(422, 'Hidden content paths are not supported')
        if item.is_symlink():
            raise HTTPException(422, 'Symbolic links are not supported')
        relative = item.relative_to(WORK / PREFIX).as_posix()
        if item.is_dir():
            checked_path(relative, section=True)
            if (item / '_index.md').is_file():
                source, kind = item / '_index.md', 'folder'
                children = tree_nodes(relative)
            elif (item / 'index.md').is_file():
                source, kind, children = item / 'index.md', 'page', []
                for asset in item.rglob('*'):
                    if asset.name.startswith('.'):
                        raise HTTPException(422, 'Hidden content paths are not supported')
                    if asset.is_symlink():
                        raise HTTPException(422, 'Symbolic links are not supported')
            else:
                raise HTTPException(422, 'Folders must contain _index.md or index.md')
        elif item.suffix == '.md' and item.name not in ('_index.md', 'index.md'):
            source, kind, children = item, 'page', []
        else:
            continue
        checked_path(source.relative_to(WORK / PREFIX).as_posix())
        metadata, body = parse(source.read_text(encoding='utf-8'))
        try:
            weight = int(metadata.get('weight', 0))
        except (ValueError, TypeError):
            raise HTTPException(422, 'Page weight must be an integer')
        result.append({'id': relative, 'path': relative, 'page_path': source.relative_to(WORK / PREFIX).as_posix(), 'kind': kind, 'title': str(metadata.get('title', item.stem)), 'weight': weight,
                       'url': document_url(source.relative_to(WORK / PREFIX).as_posix(), metadata), 'children': children})
    return sorted(result, key=lambda node: (node['weight'] == 0, node['weight'], node['title'].casefold(), node['id']))


def tree_result():
    return {'revision': content_revision(), 'nodes': tree_nodes()}


def flatten_nodes(nodes):
    return {node['id']: node for root in nodes for node in [root, *flatten_nodes(root['children']).values()]}


def section_parent(value):
    parent = checked_path(value, section=True)
    if not parent.is_dir() or not (parent / '_index.md').is_file():
        raise HTTPException(422, 'Choose an existing folder')
    checked_path('/'.join(filter(None, [value, '_index.md'])))
    return parent


def assert_available_url(url):
    wanted = url.rstrip('/')
    for node in flatten_nodes(tree_nodes()).values():
        metadata, body = parse(node_metadata(node).read_text(encoding='utf-8'))
        aliases = metadata.get('aliases', [])
        if not isinstance(aliases, list):
            raise HTTPException(422, 'Page aliases must be a list')
        urls = [node['url'], *[ORIGIN + alias for alias in aliases if isinstance(alias, str)]]
        if any(existing.rstrip('/') == wanted for existing in urls):
            raise HTTPException(409, 'This URL belongs to another page or redirect')


def renumber(nodes):
    for index, node in enumerate(nodes, 1):
        target = node_metadata(node)
        metadata, body = parse(target.read_text(encoding='utf-8'))
        if metadata.get('weight') != index * 10:
            metadata['weight'] = index * 10
            write_markdown(target, metadata, body)


def publish_structure(data, operation):
    revision = data.get('revision')
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{40}', revision):
        raise HTTPException(422, 'Content tree revision is required')
    with LOCK:
        sync()
        for attempt in range(3):
            if not hmac.compare_digest(content_revision(), revision):
                raise HTTPException(409, 'Wiki structure or content changed; reload before saving')
            try:
                extra = operation()
                git('add', '--', PREFIX)
                base = git('rev-parse', 'HEAD')
                if not git('diff', '--cached', '--name-only'):
                    return dict(tree_result(), commit=base, **extra)
                git('-c', 'user.name=' + SETTINGS.git_author, '-c', 'user.email=' + SETTINGS.git_email, 'commit', '-m', 'update wiki structure')
                commit = git('rev-parse', 'HEAD')
                result = dict(tree_result(), commit=commit, **extra)
                try:
                    if not LIVE_MODE:
                        git('push', 'origin', 'HEAD:refs/heads/' + BRANCH)
                    return result
                except RuntimeError as error:
                    sync()
                    remote = git('rev-parse', 'HEAD')
                    try:
                        git('merge-base', '--is-ancestor', commit, remote)
                        return dict(tree_result(), commit=commit, **extra)
                    except RuntimeError:
                        if remote == base:
                            raise RuntimeError('Repository push unavailable') from error
            except Exception:
                git('reset', '--hard', 'HEAD')
                git('clean', '-fd', '--', PREFIX)
                raise
        raise HTTPException(409, 'Concurrent repository update; retry saving')


@app.get('/api/editor/tree')
def get_tree():
    with LOCK:
        sync()
        return tree_result()


@app.post('/api/editor/folders')
def create_folder(data: dict):
    title, unused = fields(dict(data, body=''))
    slug, parent_id = data.get('slug'), data.get('parent', '')
    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug == 'index':
        raise HTTPException(422, 'Slug must use lowercase letters, digits and hyphens')
    def operation():
        parent = section_parent(parent_id)
        siblings = tree_nodes(parent_id)
        destination = parent / slug
        if destination.exists() or (parent / (slug + '.md')).exists():
            raise HTTPException(409, 'This name is already used')
        assert_available_url(page_url(destination.relative_to(WORK / PREFIX).as_posix() + '/_index.md'))
        destination.mkdir()
        write_markdown(destination / '_index.md', {'title': title, 'weight': (len(siblings) + 1) * 10}, '')
        renumber(siblings)
        path = destination.relative_to(WORK / PREFIX).as_posix()
        return {'path': path + '/_index.md', 'url': page_url(path + '/_index.md')}
    return publish_structure(data, operation)


def rewrite_references(documents, moved):
    import posixpath
    lookup = {}
    for path in documents:
        variants = [path, path.removesuffix('.md')]
        if Path(path).name in ('_index.md', 'index.md'):
            variants.append(str(Path(path).parent))
        for variant in variants:
            lookup[variant.strip('/')] = path
    expression = re.compile(r'({{[<%]\s*relref\s+["\'])([^"\']+)(["\']\s*[>%]}})')
    for old_path, (metadata, body) in documents.items():
        new_path = moved.get(old_path, old_path)
        old_url, new_url = document_url(old_path, metadata), document_url(new_path, metadata)
        if old_url != new_url:
            aliases = metadata.get('aliases', [])
            if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                raise HTTPException(422, 'Page aliases must be a list')
            aliases = [alias for alias in aliases if alias != new_url.removeprefix(ORIGIN)]
            previous = old_url.removeprefix(ORIGIN)
            if previous not in aliases:
                aliases.append(previous)
            metadata['aliases'] = aliases
        def replace(match):
            reference, separator, fragment = match[2].partition('#')
            relative = posixpath.normpath(posixpath.join(str(Path(old_path).parent), reference)).strip('/')
            candidates = [reference.strip('/')] if reference.startswith('/') else [relative, reference.strip('/')]
            resolved = old_path if not reference else next((lookup[candidate] for candidate in candidates if candidate in lookup), None)
            if resolved is None or (resolved not in moved and old_path not in moved):
                return match[0]
            return match[1] + '/' + moved.get(resolved, resolved) + (separator + fragment if separator else '') + match[3]
        rewritten = expression.sub(replace, body)
        if new_path != old_path or rewritten != body:
            write_markdown(checked_path(new_path), metadata, rewritten)


@app.post('/api/editor/move')
def move_node(data: dict):
    source, parent_id, before = data.get('source'), data.get('target_parent', ''), data.get('before')
    def operation():
        source_path = checked_path(source, section=True)
        if not source or Path(source).name in ('_index.md', 'index.md'):
            raise HTTPException(422, 'The root and section index cannot be moved')
        nodes = flatten_nodes(tree_nodes())
        if source not in nodes:
            raise HTTPException(404, 'Source not found')
        node = nodes[source]
        parent = section_parent(parent_id)
        if parent_id == source or parent_id.startswith(source + '/'):
            raise HTTPException(422, 'A folder cannot be moved into itself')
        old_parent = str(Path(source).parent)
        old_parent = '' if old_parent == '.' else old_parent
        siblings = [item for item in tree_nodes(parent_id) if item['id'] != source]
        if before is not None and before not in [item['id'] for item in siblings]:
            raise HTTPException(422, 'Insertion target must be a sibling')
        destination = parent / source_path.name
        destination_id = destination.relative_to(WORK / PREFIX).as_posix()
        if destination != source_path:
            collision = parent / (source_path.stem if source_path.suffix == '.md' else source_path.name + '.md')
            if destination.exists() or collision.exists():
                raise HTTPException(409, 'A page or folder with this name already exists')
            documents = {}
            for path in (WORK / PREFIX).rglob('*.md'):
                relative = path.relative_to(WORK / PREFIX).as_posix()
                checked_path(relative)
                documents[relative] = parse(path.read_text(encoding='utf-8'))
            moved = {path: destination_id + path[len(source):] for path in documents if path == source or path.startswith(source + '/')}
            occupied = {}
            for path, (metadata, body) in documents.items():
                aliases = metadata.get('aliases', [])
                if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.startswith('/') or alias.startswith('//') or '..' in alias.split('/') for alias in aliases):
                    raise HTTPException(422, 'Aliases must be absolute site paths')
                if path in moved and (metadata.get('slug') or metadata.get('url')):
                    raise HTTPException(422, 'Moving pages with custom slug or URL is not supported')
                for url in [document_url(path, metadata), *[ORIGIN + alias for alias in aliases]]:
                    occupied.setdefault(url.rstrip('/'), set()).add(path)
            for old_path, new_path in moved.items():
                metadata, body = documents[old_path]
                owners = occupied.get(document_url(new_path, metadata).rstrip('/'), set())
                if owners - {old_path}:
                    raise HTTPException(409, 'Destination URL belongs to another page or redirect')
            source_path.rename(destination)
            rewrite_references(documents, moved)
            renumber(tree_nodes(old_parent))
        node = dict(node, id=destination_id)
        index = next((index for index, item in enumerate(siblings) if item['id'] == before), len(siblings))
        siblings.insert(index, node)
        renumber(siblings)
        target = node_metadata(node)
        metadata, unused = parse(target.read_text(encoding='utf-8'))
        path = target.relative_to(WORK / PREFIX).as_posix()
        return {'path': path, 'url': document_url(path, metadata)}
    return publish_structure(data, operation)


def rename_folder(data):
    title, unused = fields(dict(data, body=''))
    if len(title) > 200 or '\r' in title:
        raise HTTPException(422, 'Folder title must contain at most 200 characters on one line')
    source = data.get('source')
    def operation():
        checked_path(source, section=True)
        node = flatten_nodes(tree_nodes()).get(source)
        if not node or node['kind'] != 'folder':
            raise HTTPException(422, 'Choose an existing folder')
        path = source + '/_index.md'
        target = checked_path(path)
        metadata, body = parse(target.read_text(encoding='utf-8'))
        metadata['title'] = title
        write_markdown(target, metadata, body)
        return {'path': path, 'url': document_url(path, metadata)}
    return publish_structure(data, operation)


def unlink_deleted_references(source, target):
    from urllib.parse import unquote, urljoin, urlsplit
    documents = {}
    lookup = {}
    deleted_urls = set()
    for path in (WORK / PREFIX).rglob('*.md'):
        relative = path.relative_to(WORK / PREFIX).as_posix()
        checked_path(relative)
        metadata, body = parse(path.read_text(encoding='utf-8'))
        documents[relative] = (metadata, body)
        variants = [relative, relative.removesuffix('.md')]
        if path.name in ('_index.md', 'index.md'):
            variants.append(str(Path(relative).parent))
        for variant in variants:
            lookup[variant.strip('/')] = relative
        if relative == source or relative.startswith(source + '/'):
            deleted_urls.add(urlsplit(document_url(relative, metadata)).path.rstrip('/'))
            deleted_urls.update(alias.rstrip('/') for alias in metadata.get('aliases', []) if isinstance(alias, str))
    if target.is_dir():
        for asset in target.rglob('*'):
            if asset.is_file() and asset.suffix != '.md':
                deleted_urls.add('/' + asset.relative_to(WORK / PREFIX).as_posix())
    shortcode = re.compile(r"{{[<%]\s*relref\s+[\"']([^\"']+)[\"']\s*[>%]}}")
    link = re.compile(r'!?\[([^]\n]*)\]\(\s*(' + shortcode.pattern + r'|[^)\n]+)\s*\)')
    code = re.compile(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*(?:\n|$)|(`+)[^`]*?\2')
    def is_deleted(path):
        return path == source or path.startswith(source + '/')
    for relative, (metadata, body) in documents.items():
        if is_deleted(relative):
            continue
        protected = [match.span() for match in code.finditer(body)]
        def referenced(match):
            reference = match[1].split('#', 1)[0]
            candidate = posixpath.normpath(posixpath.join(str(Path(relative).parent), reference)).strip('/')
            choices = [reference.strip('/')] if reference.startswith('/') else [candidate, reference.strip('/')]
            resolved = relative if not reference else next((lookup[value] for value in choices if value in lookup), None)
            return resolved is not None and is_deleted(resolved)
        def replace(match):
            if any(start <= match.start() < end for start, end in protected):
                return match[0]
            destination = match[2].strip()
            ref = shortcode.fullmatch(destination)
            if ref:
                return match[1] if referenced(ref) else match[0]
            destination = re.sub(r'\s+[\"\'][^\n]*[\"\']$', '', destination).strip('<>')
            resolved = urlsplit(urljoin(document_url(relative, metadata), destination))
            if resolved.netloc == urlsplit(ORIGIN).netloc and unquote(resolved.path).rstrip('/') in deleted_urls:
                return match[1]
            return match[0]
        rewritten = link.sub(replace, body)
        if any(referenced(match) for match in shortcode.finditer(rewritten)):
            raise HTTPException(422, 'Cannot delete: unsupported reference in ' + relative + '; remove its link first')
        if rewritten != body:
            write_markdown(checked_path(relative), metadata, rewritten)


def delete_node(data):
    source = data.get('source')
    def operation():
        target = checked_path(source, section=True)
        if not source or Path(source).name in ('_index.md', 'index.md'):
            raise HTTPException(422, 'The root and section index cannot be deleted')
        if source not in flatten_nodes(tree_nodes()):
            raise HTTPException(404, 'Source not found')
        if target.is_dir():
            for path in target.rglob('*'):
                if path.is_symlink() or not path.resolve().is_relative_to(target.resolve()):
                    raise HTTPException(400, 'Symbolic links are not supported')
                if any(part.startswith('.') for part in path.relative_to(target).parts):
                    raise HTTPException(422, 'Hidden content paths are not supported')
            unlink_deleted_references(source, target)
            shutil.rmtree(target)
        else:
            unlink_deleted_references(source, target)
            target.unlink()
        parent = str(Path(source).parent)
        renumber(tree_nodes('' if parent == '.' else parent))
        return {'path': source, 'deleted': True}
    return publish_structure(data, operation)


@app.get('/api/editor/pages')
def get_page(path: str):
    with LOCK:
        sync()
        return read_page(path)


@app.get('/api/editor/catalog')
def catalog():
    with LOCK:
        sync()
        sections = []
        for item in sorted((WORK / PREFIX).rglob('_index.md')):
            relative = item.relative_to(WORK / PREFIX).as_posix()
            checked_path(relative)
            data = read_page(relative)
            section = str(Path(relative).parent)
            sections.append({'path': '' if section == '.' else section, 'title': data['title']})
        return {'sections': sections}


@app.put('/api/editor/pages')
def update_page(data: dict):
    return save(data)


@app.post('/api/editor/pages')
def create_page(data: dict):
    return save(data, create=True)


@app.post('/api/editor/preview')
def preview(data: dict):
    title, body = fields(data)
    current = data.get('path')
    if current:
        checked_path(current)
    def relref(match):
        reference, separator, fragment = match[1].partition('#')
        if not reference:
            return '#' + fragment
        relative = posixpath.normpath(posixpath.join(str(Path(current).parent) if current else '', reference))
        candidates = [reference.lstrip('/')] if reference.startswith('/') else [relative, reference]
        for candidate in candidates:
            variants = [candidate] if candidate.endswith('.md') else [candidate + '.md', candidate.rstrip('/') + '/_index.md', candidate.rstrip('/') + '/index.md']
            for variant in variants:
                try:
                    target = checked_path(variant)
                except HTTPException:
                    continue
                if target.is_file():
                    metadata, unused = parse(target.read_text(encoding='utf-8'))
                    return document_url(variant, metadata) + (separator + fragment if separator else '')
        raise HTTPException(422, 'Referenced page not found')
    with LOCK:
        body = re.sub(r"{{[<%]\s*relref\s+[\"']([^\"']+)[\"']\s*[>%]}}", relref, body)
    renderer = MarkdownIt('commonmark', {'html': False}).enable('table')
    tokens = renderer.parse(body)
    identifiers = set()
    for index, token in enumerate(tokens):
        if token.type != 'heading_open':
            continue
        children = tokens[index + 1].children or []
        text = ''.join(child.content for child in children if child.type in ('text', 'code_inline', 'image'))
        base = ''.join(character for character in text.lower() if character.isalnum() or character in '-_ ' or character.isspace())
        base = re.sub(r'\s', '-', base.strip())
        identifier = base
        suffix = 1
        while identifier in identifiers:
            identifier = base + '-' + str(suffix)
            suffix += 1
        identifiers.add(identifier)
        token.attrSet('id', identifier)
    return {'html': renderer.renderer.render(tokens, renderer.options, {}), 'approximate': True}


@app.get('/api/editor/publications/{commit}')
def publication(commit: str):
    if LIVE_MODE:
        if not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise HTTPException(400, 'Invalid publication')
        path = LIVE.root / 'snapshots' / commit / 'state.json'
        if not path.is_file():
            raise HTTPException(404, 'Publication not found')
        state = json.loads(path.read_text())
        return {'status': 'published', 'url': ORIGIN + '/', 'git_status': ('pending' if state['pending'] else 'synced') if REPO else 'disabled', 'git_error': state.get('error')}
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise HTTPException(400, 'Invalid commit')
    try:
        with urllib.request.urlopen(ORIGIN + '/version.json', timeout=10) as response:
            published = json.load(response).get('source_sha', '')
        if published == commit:
            status = 'published'
        elif re.fullmatch(r'[a-f0-9]{40}', published):
            with LOCK:
                sync()
                try:
                    git('merge-base', '--is-ancestor', commit, published)
                    status = 'published'
                except RuntimeError:
                    status = 'pending'
        else:
            status = 'pending'
    except Exception:
        status = 'pending'
    return {'status': status, 'url': ORIGIN + '/'}


@app.post('/api/editor/uploads')
def upload(data: dict, request: Request):
    return UPLOADS.stage(data, request.state.auth['user']['id'])


@app.post('/api/editor/batch')
def batch(data: dict, request: Request):
    uploads = data.get('uploads', [])
    if not isinstance(uploads, list) or len(uploads) > 100 or any(not isinstance(item, str) for item in uploads):
        raise HTTPException(422, 'Provide at most 100 upload identifiers')
    uploads = list(dict.fromkeys(uploads))
    owner = request.state.auth['user']['id']
    attachments = [UPLOADS.checked(identifier, owner) for identifier in uploads]
    pages = data.get('pages', [])
    operations = data.get('operations', [])
    if not isinstance(pages, list) or len(pages) > 100 or any(not isinstance(page, dict) for page in pages):
        raise HTTPException(422, 'Provide at most 100 pages')
    if not isinstance(operations, list) or len(operations) > 100 or any(not isinstance(item, dict) or item.get('type') not in ('folder', 'move', 'delete', 'rename') for item in operations):
        raise HTTPException(422, 'Provide at most 100 folder, move, delete or rename operations')
    if not pages and not operations and not uploads:
        raise HTTPException(422, 'Provide pages or structure operations')
    if operations and (not isinstance(data.get('tree_revision'), str) or not re.fullmatch(r'[a-f0-9]{40}', data['tree_revision'])):
        raise HTTPException(422, 'Content tree revision is required')
    if not LIVE_MODE:
        raise HTTPException(503, 'Workspace publication requires live mode')
    def operation():
        base_revision = content_revision()
        if data.get('tree_revision') and data['tree_revision'] != base_revision:
            raise HTTPException(409, 'Wiki structure or content changed')
        for attachment in attachments:
            target = WORK / PREFIX / attachment.name
            if target.exists() and target.read_bytes() != attachment.read_bytes():
                raise HTTPException(409, 'Attachment already exists with different content')
            shutil.copyfile(attachment, target)
        if attachments:
            git('add', '--', PREFIX)
            if git('diff', '--cached', '--name-only'):
                LIVE.commit('add wiki attachments')
        results = []
        paths = set()
        for page in pages:
            if 'path' in page:
                path = page['path']
            else:
                section, slug = page.get('section', ''), page.get('slug')
                checked_path(section, section=True)
                if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
                    raise HTTPException(422, 'Slug must use lowercase letters, digits and hyphens')
                path = '/'.join(filter(None, [section, slug + '.md']))
            checked_path(path)
            if path in paths:
                raise HTTPException(422, 'Duplicate page in workspace')
            paths.add(path)
            fields(page)
            if 'path' in page:
                revision = page.get('revision')
                if not isinstance(revision, str):
                    raise HTTPException(422, 'Base revision is required')
                if not hmac.compare_digest(read_page(path)['revision'], revision):
                    raise HTTPException(409, 'Page changed since it was opened; reload before saving')
            if page.get('tree_revision') and page['tree_revision'] != base_revision:
                raise HTTPException(409, 'Wiki structure or content changed')
        for page in pages:
            payload = {key: value for key, value in page.items() if key != 'tree_revision'}
            if 'path' in page:
                payload['revision'] = read_page(page['path'])['revision']
            result = save(payload, create='path' not in page)
            results.append(dict(result, original_path=result['path']))
        for item in operations:
            payload = dict(item, revision=content_revision())
            if item['type'] == 'folder':
                create_folder(payload)
            elif item['type'] == 'rename':
                rename_folder(payload)
            elif item['type'] == 'delete':
                delete_node(payload)
                source = item['source']
                for result in results:
                    if result['path'] == source or result['path'].startswith(source + '/'):
                        result['deleted'] = True
            else:
                move_node(payload)
                source = item['source']
                destination = '/'.join(filter(None, [item.get('target_parent', ''), Path(source).name]))
                for result in results:
                    path = result['path']
                    if not result.get('deleted') and (path == source or path.startswith(source + '/')):
                        result['path'] = destination + path[len(source):]
        for result in results:
            if result.get('deleted'):
                deleted = {key: result[key] for key in ('original_path', 'path', 'deleted')}
                result.clear()
                result.update(deleted)
                continue
            path = result['path']
            metadata, unused = parse(checked_path(path).read_text(encoding='utf-8'))
            result.update(read_page(path), url=document_url(path, metadata), commit=git('rev-parse', 'HEAD'))
        return dict(tree_result(), pages=results, url=ORIGIN + '/')
    return LIVE.transaction(operation, actor=request.state.auth['user'])()


@app.get('/api/editor/sync')
def sync_status():
    if not LIVE_MODE:
        return {'mode': 'git'}
    with LOCK:
        pending = LIVE.pending()
        path = LIVE.root / 'sync.json'
        state = json.loads(path.read_text()) if path.exists() else {}
        return {'mode': 'live', 'git_enabled': bool(REPO), 'pending': len(pending), 'error': next((item['error'] for path, item in pending if item.get('error')), state.get('error')), 'last_attempt': state.get('time')}


@app.api_route('/site/{path:path}', methods=['GET', 'HEAD'])
def live_site(path: str):
    if not LIVE_MODE:
        raise HTTPException(404)
    return LIVE.file(path)


@app.get('/healthz')
def health():
    if not LIVE_MODE or not LIVE or not LIVE.started:
        raise HTTPException(503)
    return {'ready': True}


if LIVE_MODE:
    from live import LiveWiki, RuntimeServices
    LIVE = LiveWiki(RuntimeServices(WORK, PREFIX, LOCK, ORIGIN, BRANCH, REPO, raw_git, tree_nodes, SETTINGS.git_author, SETTINGS.git_email), root=SETTINGS.state_dir, template=SETTINGS.template_dir)
    save = LIVE.transaction(save)
    publish_structure = LIVE.transaction(publish_structure)
    app.add_event_handler('startup', LIVE.start)
    app.add_event_handler('shutdown', LIVE.close)

from auth import install_auth

AUTH = install_auth(app, origin=ORIGIN, base_path=SETTINGS.base_path, data_dir=SETTINGS.data_dir, public=SETTINGS.public, bootstrap_secret=SETTINGS.bootstrap_secret)


@app.middleware('http')
async def base_path(request: Request, call_next):
    prefix = SETTINGS.base_path
    path = request.scope['path']
    if prefix and path != '/healthz':
        if path != prefix and not path.startswith(prefix + '/'):
            return Response(status_code=404)
        request.scope['path'] = path[len(prefix):] or '/'
        request.scope['root_path'] = prefix
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > (12 if request.scope['path'] == '/api/editor/uploads' else 2) * 1024 * 1024:
                return Response(status_code=413)
            chunks.append(chunk)
        request._body = b''.join(chunks)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.api_route('/{path:path}', methods=['GET', 'HEAD'])
def site(path: str, request: Request):
    if not LIVE_MODE:
        raise HTTPException(404)
    try:
        return LIVE.file(path)
    except HTTPException as error:
        if error.status_code != 404 or not path.startswith('upload-') or '/' in path or not request.state.auth:
            raise
        return UPLOADS.preview(path, request.state.auth['user']['id'])
