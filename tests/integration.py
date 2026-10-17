import json
import hashlib
import os
import subprocess
import sys
import tempfile
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
REVISION = os.environ.get('THEME_REVISION')


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def attributes(self, tag, **match):
        return [attrs for element, attrs in self.elements if element == tag and all(attrs.get(key) == value for key, value in match.items())]


def run(*args, cwd):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def write(site, name, text):
    path = site / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def check_site(site, language):
    run(sys.executable, str(ROOT / 'scripts/new_site.py'), str(site), '--title', 'Test & Docs', '--language', language, cwd=ROOT)
    config = site / 'hugo.toml'
    config.write_text(config.read_text().replace('http://localhost:1320/', 'https://example.test/docs/').replace("logo = ''", "logo = 'custom.svg'").replace("footer = ''", "footer = 'Test footer'").replace('noindex = true', f'noindex = {str(language == "ru").lower()}'))
    module = site / 'go.mod'
    if REVISION:
        run('go', 'mod', 'edit', '-droprequire=github.com/alchemmist/hugo-docs', cwd=site)
        run('go', 'get', f'github.com/alchemmist/hugo-docs@{REVISION}', cwd=site)
    else:
        module.write_text(module.read_text() + f'\nreplace github.com/alchemmist/hugo-docs => {ROOT}\n')
    write(site, 'static/custom.svg', '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5"/></svg>')
    write(site, 'content/engineering/_index.md', '---\ntitle: Engineering\nweight: 20\n---\nFolder prose must never be published.\n')
    write(site, 'content/engineering/reliability/_index.md', '---\ntitle: Reliability\nweight: 10\n---\n')
    write(site, 'content/engineering/reliability/timeouts.md', '''---
title: Timeouts
weight: 10
---

## Retry budget

English and русский searchable content. $a^2 + b^2 = c^2$.

```mermaid
flowchart LR
  A --> B
```

[First note]({{< relref "getting-started/first-note.md" >}})
''')
    write(site, 'content/engineering/secret.md', '---\ntitle: Unpublished secret\ndraft: true\n---\nNever publish this draft.\n')
    write(site, 'layouts/partials/docs/head-extra.html', '<meta name="consumer-hook" content="works">')
    run('hugo', '--minify', cwd=site)
    public = site / 'public'
    home = (public / 'index.html').read_text()
    page = (public / 'engineering/reliability/timeouts/index.html').read_text()
    document = Document(page)
    assert 'Test & Docs' in unescape(page) and 'Test footer' in page
    assert 'consumer-hook' in page
    assert 'Folder prose' not in page
    assert not (public / 'engineering/index.html').exists()
    assert not (public / 'engineering/reliability/index.html').exists()
    assert not (public / 'engineering/secret/index.html').exists()
    assert not (public / 'reference').exists()
    assert not (public / 'start').exists()
    assert not (public / 'getting-started/index.html').exists()
    assert ('noindex, nofollow' in home) == (language == 'ru')
    assert ('Disallow: /' in (public / 'robots.txt').read_text()) == (language == 'ru')
    assert ('Найти страницу' if language == 'ru' else 'Find a page') in home
    body = document.attributes('body')[0]
    assert body['data-search-index'] == '/docs/search-index.json'
    ui = json.loads(body['data-ui'])
    assert ui['openNavigation'] == ('Открыть навигацию' if language == 'ru' else 'Open navigation')
    buttons = document.attributes('button', **{'class': 'tree-toggle'})
    assert len({button['aria-controls'] for button in buttons}) == len(buttons)
    assert next(button for button in buttons if button['data-title'] == 'Reliability')['aria-expanded'] == 'true'
    links = [item.get('href', '') for item in document.attributes('a')]
    assert '/docs/engineering/' not in links and '/docs/engineering/reliability/' not in links
    assert '/docs/getting-started/first-note/' in links
    index = json.loads((public / 'search-index.json').read_text())
    assert {item['url'] for item in index} == {'/docs/', '/docs/getting-started/first-note/', '/docs/engineering/reliability/timeouts/'}
    assert 'searchable content' in next(item['content'] for item in index if item['title'] == 'Timeouts')
    for file in public.rglob('*.html'):
        for tag, attrs in Document(file.read_text()).elements:
            for field in ('href', 'src'):
                url = attrs.get(field, '')
                if url.startswith(('#', 'data:', 'mailto:')) or not url:
                    continue
                parsed = urlparse(url)
                if parsed.scheme:
                    assert parsed.netloc == 'example.test', f'External asset or link: {url}'
                path = unquote(parsed.path)
                assert path.startswith('/docs/'), f'Path escaped baseURL: {url}'
                target = public / path.removeprefix('/docs/')
                assert target.is_file() or (target / 'index.html').is_file(), f'Broken URL: {url}'
    fonts = list((public / 'hugo-content/fonts').glob('*.woff2'))
    assert len(fonts) == 5
    for font in fonts:
        assert hashlib.sha256(font.read_bytes()).hexdigest() in font.name
    assert 'wiki-editor' not in home
    for path in ['hugo-content/lib/mermaid.js', 'hugo-content/lib/mathjax/tex-svg.js', 'hugo-content/lib/zoom.js']:
        assert (public / path).is_file(), path
    assert 'class=mermaid' in page or 'class="mermaid"' in page
    run('hugo', 'new', 'content', 'engineering/generated.md', cwd=site)
    assert 'title:' in (site / 'content/engineering/generated.md').read_text()
    original = config.read_bytes()
    duplicate = subprocess.run([sys.executable, str(ROOT / 'scripts/new_site.py'), str(site)], capture_output=True)
    assert duplicate.returncode != 0 and original == config.read_bytes()
    print(f'{language}: independent site, subpath, folders, search, branding, hooks, drafts, local assets, and scaffold passed')


with tempfile.TemporaryDirectory(prefix='hugo-docs-test-') as directory:
    for language in ('en', 'ru'):
        check_site(Path(directory) / language, language)
print('All integration checks passed')
