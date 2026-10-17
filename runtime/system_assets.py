import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

SHELLS = frozenset(f'{page}.{language}.html' for page in ('login', 'admin') for language in ('en', 'ru'))
EXTENSIONS = frozenset(('.css', '.js', '.woff', '.woff2', '.ttf', '.otf', '.svg', '.png', '.ico'))
CSS_URL = re.compile(r'url\(\s*([\'"]?)(.*?)\1\s*\)', re.IGNORECASE)


class ResourceGraph:
    def __init__(self, public, output, base_path):
        self.public = public.resolve()
        self.output = output
        self.prefix = '/' + base_path.strip('/') if base_path.strip('/') else ''
        self.visiting = set()
        self.copied = {}
        self.manifest = {}

    def resolve(self, url, parent):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError('External or fragmented system resource')
        path = unquote(parsed.path)
        if '\\' in path or any(part == '..' for part in Path(path).parts):
            raise ValueError('Unsafe system resource path')
        if path.startswith('/'):
            if self.prefix:
                if not path.startswith(self.prefix + '/'):
                    raise ValueError('System resource outside base path')
                path = path[len(self.prefix):]
            target = self.public / path.lstrip('/')
        else:
            target = parent / path
        source = target.resolve()
        if not source.is_relative_to(self.public) or source.suffix.lower() not in EXTENSIONS or not source.is_file():
            raise ValueError('Missing or unsafe system resource')
        return source

    def copy(self, url, parent):
        source = self.resolve(url, parent)
        if source in self.copied:
            return self.copied[source]
        if source in self.visiting:
            raise ValueError('Circular system resource dependency')
        self.visiting.add(source)
        content = source.read_bytes()
        if source.suffix.lower() == '.css':
            text = content.decode('utf-8')
            if re.search(r'@import\b', text, re.IGNORECASE):
                raise ValueError('System stylesheets must bundle imports')
            for match in CSS_URL.finditer(text):
                self.copy(match.group(2).strip(), source.parent)
        name = hashlib.sha256(content).hexdigest() + source.suffix.lower()
        (self.output / 'assets' / name).write_bytes(content)
        route = '/' + source.relative_to(self.public).as_posix()
        self.manifest[route] = 'assets/' + name
        result = self.prefix + route
        self.copied[source] = result
        self.visiting.remove(source)
        return result


class ShellParser(HTMLParser):
    def __init__(self, graph):
        super().__init__(convert_charrefs=False)
        self.graph = graph
        self.parts = []

    def tag(self, tag, attrs, closing=False):
        values = dict(attrs)
        resource = 'src' if tag == 'script' and values.get('src') else None
        relations = set((values.get('rel') or '').lower().split())
        if tag == 'link' and relations & {'stylesheet', 'preload', 'modulepreload', 'icon'}:
            resource = 'href'
        if resource == 'href' and 'icon' in relations and values.get(resource) == 'data:,':
            resource = None
        if resource:
            if not values.get(resource):
                raise ValueError('Missing system resource URL')
            values[resource] = self.graph.copy(values[resource], self.graph.public)
            attrs = [(key, values[key]) for key, value in attrs]
        attributes = ''.join(' ' + key + ('' if value is None else '="' + escape(value, quote=True) + '"') for key, value in attrs)
        self.parts.append('<' + tag + attributes + ('/>' if closing else '>'))

    def handle_starttag(self, tag, attrs):
        self.tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self.tag(tag, attrs, True)

    def handle_endtag(self, tag):
        self.parts.append('</' + tag + '>')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append('&' + name + ';')

    def handle_charref(self, name):
        self.parts.append('&#' + name + ';')

    def handle_decl(self, decl):
        self.parts.append('<!' + decl + '>')

    def handle_comment(self, data):
        self.parts.append('<!--' + data + '-->')


def extract_system_pages(destination, base_path=''):
    destination = Path(destination)
    public = destination / 'public'
    source = public / 'wiki-system.json'
    if source.is_symlink() or not source.is_file():
        raise ValueError('Missing system pages')
    shells = json.loads(source.read_text())
    language = shells.pop('_language', None) if isinstance(shells, dict) else None
    if language is not None:
        language = language.lower().split('-')[0] if isinstance(language, str) else 'en'
        language = language if language in ('en', 'ru') else 'en'
    if not isinstance(shells, dict) or set(shells) != SHELLS or not all(isinstance(value, str) for value in shells.values()):
        raise ValueError('Invalid system pages')
    output = destination / 'system-pages'
    (output / 'assets').mkdir(parents=True, exist_ok=True)
    if language is not None:
        (output / 'language.txt').write_text(language)
    graph = ResourceGraph(public, output, base_path)
    for name, content in shells.items():
        parser = ShellParser(graph)
        parser.feed(content)
        parser.close()
        (output / name).write_text(''.join(parser.parts))
    (output / 'public-assets.json').write_text(json.dumps(graph.manifest, sort_keys=True))
    source.unlink()
