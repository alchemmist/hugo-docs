import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ruamel.yaml import YAML


def boolean(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('true', '1', 'yes')


@dataclass(frozen=True)
class Settings:
    public_url: str
    data_dir: Path
    work_dir: Path
    state_dir: Path
    template_dir: Path
    content_prefix: str
    repository: str
    branch: str
    git_author: str
    git_email: str
    public: bool
    bootstrap_secret: str
    live: bool

    @property
    def base_path(self):
        return urlsplit(self.public_url).path.rstrip('/')

    @classmethod
    def load(cls):
        location = Path(os.getenv('WIKI_CONFIG', '/config/wiki.yaml'))
        raw = YAML(typ='safe').load(location.read_text()) if location.is_file() else {}
        raw = raw or {}
        if not isinstance(raw, dict):
            raise ValueError('wiki.yaml must contain a mapping')
        storage = raw.get('storage', {})
        remote = raw.get('git', {})
        auth = raw.get('auth', {})
        url = os.getenv('PUBLIC_ORIGIN', raw.get('url', 'http://localhost:8080')).rstrip('/')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username or '..' in parsed.path.split('/'):
            raise ValueError('Wiki URL must be an absolute HTTP(S) URL without credentials, query or fragment')
        data = Path(os.getenv('WIKI_DATA_DIR', storage.get('path', '/data')))
        prefix = os.getenv('CONTENT_PREFIX', storage.get('content_prefix', 'content'))
        if not prefix or Path(prefix).is_absolute() or any(part in ('', '.', '..') or part.startswith('.') for part in prefix.split('/')) or '\\' in prefix:
            raise ValueError('Content prefix must be a safe relative directory')
        secret_file = Path(os.getenv('WIKI_BOOTSTRAP_SECRET_FILE') or auth.get('bootstrap_secret_file') or str(data / 'bootstrap-token'))
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(secrets.token_urlsafe(32) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        secret = secret_file.read_text().strip()
        return cls(url, data, Path(os.getenv('WORK_DIR', str(data / 'repository'))), Path(os.getenv('LIVE_STATE_DIR', str(data / 'live'))), Path(os.getenv('LIVE_TEMPLATE_DIR', raw.get('site', '/opt/wiki'))), prefix, os.getenv('GIT_REPOSITORY', remote.get('repository', '')), os.getenv('GIT_BRANCH', remote.get('branch', 'main')), os.getenv('GIT_AUTHOR_NAME', remote.get('author', 'Wiki')), os.getenv('GIT_AUTHOR_EMAIL', remote.get('email', 'wiki@localhost')), boolean(os.getenv('WIKI_PUBLIC', raw.get('public', True))), secret, boolean(os.getenv('LIVE_MODE', 'true')))
