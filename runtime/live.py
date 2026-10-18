from dataclasses import dataclass
from typing import Callable
import functools
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from audit import CURRENT_ACTOR
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from theme import apply_theme


@dataclass
class RuntimeServices:
    WORK: Path
    PREFIX: str
    LOCK: object
    ORIGIN: str
    BRANCH: str
    REPO: str
    raw_git: Callable
    tree_nodes: Callable
    author: str = 'Wiki'
    email: str = 'wiki@localhost'


class LiveWiki:
    def __init__(self, services, *, root, template):
        self.services = services
        self.root = root
        self.template = template
        self.remote = self.root / 'remote'
        self.current = self.root / 'current'
        self.wake = threading.Event()
        self.depth = 0
        self.started = False
        self.stopping = threading.Event()
        self.worker = None
        self.writer_lock = None

    def durable_json(self, path, data):
        temporary = path.with_suffix('.tmp')
        with temporary.open('w') as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def initialize(self):
        with self.services.LOCK:
            if self.started:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            work = self.services.WORK
            if not (work / '.git').exists():
                work.mkdir(parents=True, exist_ok=True)
                content = work / self.services.PREFIX
                content.parent.mkdir(parents=True, exist_ok=True)
                if not content.exists():
                    shutil.copytree(self.template / 'content', content)
                self.services.raw_git('init', cwd=work)
                self.services.raw_git('add', '--', self.services.PREFIX)
                self.commit('initialize live wiki')
            if self.current.exists():
                state = json.loads((self.current / 'state.json').read_text())
                self.services.raw_git('reset', '--hard', state['commit'])
                self.services.raw_git('clean', '-fd', '--', self.services.PREFIX)
                self.publish(state['commit'], state['commit'], pending=False)
            else:
                commit = self.services.raw_git('rev-parse', 'HEAD')
                self.publish(commit, commit, pending=False)
            self.started = True

    def commit(self, message):
        return self.services.raw_git('-c', 'user.name=' + self.services.author, '-c', 'user.email=' + self.services.email, 'commit', '-m', message)

    def build(self, destination):
        self.services.tree_nodes()
        env = dict(os.environ, HUGO_MODULE_PROXY='off', GOPROXY='off', HUGO_CACHEDIR=str(self.root / 'hugo-cache'), HUGO_RESOURCEDIR=str(self.root / 'hugo-resources'))
        system_config = self.root / 'system-outputs.toml'
        system_config.write_text("[outputs]\nhome = ['HTML', 'SearchIndex', 'WikiSystem']\n")
        result = subprocess.run([os.getenv('HUGO_BINARY', 'hugo'), '--source', str(self.template), '--config', 'hugo.toml,' + str(system_config), '--contentDir', str(self.services.WORK / self.services.PREFIX), '--destination', str(destination / 'public'), '--baseURL', self.services.ORIGIN + '/', '--noBuildLock'], env=env, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise HTTPException(422, 'Wiki cannot be published: ' + result.stderr[-1500:])
        from system_assets import extract_system_pages
        from urllib.parse import urlsplit
        extract_system_pages(destination, urlsplit(self.services.ORIGIN).path.rstrip('/'))

    def publish(self, base, commit, pending=True, actor=None):
        destination = self.root / 'snapshots' / commit
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            destination = destination.with_name(commit + '-' + uuid.uuid4().hex)
        destination.mkdir()
        previous = self.current.resolve() if self.current.exists() else None
        try:
            self.build(destination)
            self.durable_json(destination / 'public' / 'version.json', {'source_sha': commit})
            self.durable_json(destination / 'state.json', {'base': base, 'commit': commit, 'pending': pending, 'created': time.time(), 'error': None, 'actor': actor or CURRENT_ACTOR.get(), 'patch_id': uuid.uuid4().hex})
            self.fsync_tree(self.services.WORK / '.git')
            self.fsync_directory(self.services.WORK)
            self.fsync_directory(self.services.WORK.parent)
            self.fsync_directory(destination.parent)
            link = self.root / 'next'
            link.unlink(missing_ok=True)
            link.symlink_to(destination)
            os.replace(link, self.current)
            descriptor = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except Exception:
            if self.current.resolve() == destination:
                if previous is None:
                    self.current.unlink(missing_ok=True)
                else:
                    rollback = self.root / 'rollback'
                    rollback.unlink(missing_ok=True)
                    rollback.symlink_to(previous)
                    os.replace(rollback, self.current)
            shutil.rmtree(destination, ignore_errors=True)
            raise
        try:
            self.cleanup()
        except OSError:
            pass
        self.wake.set()

    def cleanup(self):
        snapshots = sorted((self.root / 'snapshots').iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
        keep = {self.current.resolve(), *snapshots[:3]}
        for path in snapshots:
            if path not in keep:
                shutil.rmtree(path / 'public', ignore_errors=True)

    def fsync_directory(self, path):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def fsync_tree(self, root):
        directories = [root]
        for path in root.rglob('*'):
            if path.is_symlink():
                raise RuntimeError('Symbolic links are not supported in publication state')
            if path.is_dir():
                directories.append(path)
            elif path.is_file():
                with path.open('rb') as handle:
                    os.fsync(handle.fileno())
        for path in reversed(directories):
            self.fsync_directory(path)

    def safe_remote_path(self, path):
        target = self.remote / path
        for part in [target, *target.parents]:
            if part == self.remote:
                break
            if part.is_symlink():
                raise RuntimeError('Remote content contains a symbolic link')
        return target

    def transaction(self, operation, actor=None):
        @functools.wraps(operation)
        def wrapped(*args, **kwargs):
            with self.services.LOCK:
                self.initialize()
                if self.depth:
                    return operation(*args, **kwargs)
                base = self.services.raw_git('rev-parse', 'HEAD')
                self.depth += 1
                try:
                    result = operation(*args, **kwargs)
                    commit = self.services.raw_git('rev-parse', 'HEAD')
                    if commit != base:
                        self.publish(base, commit, actor=actor)
                    return dict(result, commit=commit, status='published')
                except Exception:
                    self.services.raw_git('reset', '--hard', base)
                    self.services.raw_git('clean', '-fd', '--', self.services.PREFIX)
                    raise
                finally:
                    self.depth -= 1
        return wrapped

    def file(self, path, theme='light'):
        if not self.started:
            raise HTTPException(503, 'Wiki is starting')
        parts = path.split('/')
        if any(part in ('.', '..') or part.startswith('.') for part in parts if part) or '\\' in path:
            raise HTTPException(404)
        root = (self.current / 'public').resolve()
        target = root / path
        if target.is_dir():
            target = target / 'index.html'
        try:
            valid = target.resolve().is_relative_to(root) and target.is_file()
        except (OSError, RuntimeError):
            valid = False
        if not valid:
            raise HTTPException(404)
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        if re.search(r'\.[a-f0-9]{8,}\.', target.name) and target.suffix in ('.css', '.js', '.woff', '.woff2'):
            headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        if target.name.startswith('upload-'):
            headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
            if target.suffix == '.pdf':
                headers['Content-Disposition'] = 'attachment'
        if target.suffix.lower() == '.html' and not target.name.startswith('upload-'):
            headers['Vary'] = 'Cookie'
            return HTMLResponse(apply_theme(target.read_text(), theme), headers=headers)
        return FileResponse(target, media_type='font/woff2' if target.suffix == '.woff2' else None, headers=headers)

    def pending(self):
        if not self.services.REPO:
            return []
        with self.services.LOCK:
            states = []
            for path in (self.root / 'snapshots').glob('*/state.json'):
                state = json.loads(path.read_text())
                if state['pending']:
                    active = json.loads((self.current / 'state.json').read_text())['commit']
                    try:
                        self.services.raw_git('merge-base', '--is-ancestor', state['commit'], active)
                    except RuntimeError:
                        continue
                    states.append((path, state))
            return sorted(states, key=lambda pair: pair[1]['created'])

    def blob(self, revision, path, cwd):
        entry = self.services.raw_git('ls-tree', revision, '--', path, cwd=cwd)
        if not entry:
            return None
        if not entry.startswith('100644 blob ') and not entry.startswith('100755 blob '):
            raise RuntimeError('Unsupported remote file type')
        result = subprocess.run(['git', 'show', revision + ':' + path], cwd=cwd, capture_output=True, timeout=30, check=True)
        return result.stdout

    def synchronize(self):
        if not self.services.REPO:
            return
        git = self.services.raw_git
        if not (self.remote / '.git').exists():
            git('clone', '--branch', self.services.BRANCH, '--single-branch', '--', self.services.REPO, str(self.remote), cwd=self.root)
        git('fetch', 'origin', self.services.BRANCH, cwd=self.remote)
        git('reset', '--hard', 'origin/' + self.services.BRANCH, cwd=self.remote)
        git('clean', '-fd', '--', self.services.PREFIX, cwd=self.remote)
        for state_path, state in self.pending():
            changed = [path for path in git('diff', '--no-renames', '--name-only', '-z', state['base'], state['commit'], '--', self.services.PREFIX).split('\0') if path]
            updates = []
            for path in changed:
                before = self.blob(state['base'], path, self.services.WORK)
                after = self.blob(state['commit'], path, self.services.WORK)
                remote = self.blob('HEAD', path, self.remote)
                if remote not in (before, after):
                    state['error'] = 'Concurrent Git changes: ' + path
                    self.durable_json(state_path, state)
                    return
                updates.append((path, after))
            for path, after in updates:
                target = self.safe_remote_path(path)
                if after is None:
                    target.unlink(missing_ok=True)
                    parent = target.parent
                    while parent != self.remote / self.services.PREFIX:
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(after)
            git('add', '--', self.services.PREFIX, cwd=self.remote)
            if git('diff', '--cached', '--name-only', cwd=self.remote):
                git('-c', 'user.name=' + self.services.author, '-c', 'user.email=' + self.services.email, 'commit', '-m', 'publish wiki workspace', cwd=self.remote)
                git('push', 'origin', 'HEAD:refs/heads/' + self.services.BRANCH, cwd=self.remote)
            state.update(pending=False, error=None, git_commit=git('rev-parse', 'HEAD', cwd=self.remote))
            self.durable_json(state_path, state)
        with self.services.LOCK:
            if self.pending():
                return
            source = self.safe_remote_path(self.services.PREFIX)
            target = self.services.WORK / self.services.PREFIX
            base = git('rev-parse', 'HEAD')
            try:
                shutil.rmtree(target)
                shutil.copytree(source, target, symlinks=True)
                self.services.tree_nodes()
                git('add', '--', self.services.PREFIX)
                if git('diff', '--cached', '--name-only'):
                    self.commit('refresh wiki from git')
                    self.publish(base, git('rev-parse', 'HEAD'), pending=False)
            except Exception:
                git('reset', '--hard', base)
                git('clean', '-fd', '--', self.services.PREFIX)
                raise

    def run(self):
        while not self.stopping.is_set():
            try:
                self.synchronize()
                self.durable_json(self.root / 'sync.json', {'error': None, 'time': time.time()})
            except Exception as error:
                self.durable_json(self.root / 'sync.json', {'error': str(error), 'time': time.time()})
            self.wake.wait(30)
            self.wake.clear()

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock = (self.root / 'writer.lock').open('a')
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            lock.close()
            raise RuntimeError('Wiki data is already in use; run exactly one writer process') from error
        self.writer_lock = lock
        try:
            self.initialize()
            self.stopping.clear()
            if self.services.REPO:
                self.worker = threading.Thread(target=self.run, daemon=True, name='wiki-git-outbox')
                self.worker.start()
        except Exception:
            self.close()
            raise

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.worker:
            self.worker.join(timeout=95)
            if self.worker.is_alive():
                return
            self.worker = None
        if self.writer_lock:
            fcntl.flock(self.writer_lock.fileno(), fcntl.LOCK_UN)
            self.writer_lock.close()
            self.writer_lock = None
