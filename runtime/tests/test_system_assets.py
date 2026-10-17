import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from system_assets import SHELLS, extract_system_pages


class SystemAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.public = self.root / 'public'
        self.public.mkdir()
        (self.public / 'theme.css').write_text('@font-face{src:url("font.woff2")}')
        (self.public / 'font.woff2').write_bytes(b'font')
        (self.public / 'app.js').write_text('document.title="wiki"')

    def manifest(self, html):
        (self.public / 'wiki-system.json').write_text(json.dumps(dict.fromkeys(SHELLS, html)))

    def test_copies_closed_graph_preserves_navigation_and_rewrites_subpath(self):
        self.manifest('<!doctype html><html><link rel="stylesheet" href="/docs/theme.css" integrity="old"><script src="/docs/app.js" integrity="old"></script><a href="/docs/private/">Wiki</a></html>')
        extract_system_pages(self.root, '/docs')
        output = self.root / 'system-pages'
        assets = json.loads((output / 'public-assets.json').read_text())
        self.assertEqual(len(assets), 3)
        page = (output / 'login.en.html').read_text()
        self.assertIn('href="/docs/theme.css"', page)
        self.assertIn('src="/docs/app.js"', page)
        self.assertIn('href="/docs/private/"', page)
        self.assertIn('integrity="old"', page)
        self.assertFalse((self.public / 'wiki-system.json').exists())
        stylesheet = next((output / 'assets').glob('*.css')).read_text()
        self.assertEqual(stylesheet, (self.public / 'theme.css').read_text())
        self.assertEqual(set(assets), {'/theme.css', '/font.woff2', '/app.js'})
        for url, filename in assets.items():
            self.assertEqual((output / filename).read_bytes(), (self.public / url.lstrip('/')).read_bytes())
        for name in SHELLS:
            self.assertTrue((output / name).is_file())

    def test_rejects_external_traversal_private_content_and_symlink_escape(self):
        outside = self.root / 'outside.css'
        outside.write_text('secret')
        (self.public / 'escape.css').symlink_to(outside)
        for url in ('https://evil.example/x.css', '//evil.example/x.css', '../outside.css', '/%2e%2e/outside.css', '/escape.css', '/private.html'):
            with self.subTest(url=url):
                self.manifest(f'<link rel="stylesheet" href="{url}">')
                with self.assertRaises(ValueError):
                    extract_system_pages(self.root)

    def test_rejects_external_css_dependencies_and_imports(self):
        for css in ('body{background:url(https://evil.example/x.woff2)}', '@import "other.css";', 'body{background:url(../outside.woff2)}'):
            with self.subTest(css=css):
                (self.public / 'theme.css').write_text(css)
                self.manifest('<link rel="stylesheet" href="/theme.css">')
                with self.assertRaises(ValueError):
                    extract_system_pages(self.root)

    def test_selected_favicon_copies_original_bytes_and_empty_icon_needs_no_asset(self):
        (self.public / 'icon.svg').write_text('<svg></svg>')
        (self.public / 'private.png').write_bytes(b'private')
        self.manifest('<link rel="icon" href="/icon.svg"><link rel="icon" href="data:,">')
        extract_system_pages(self.root)
        output = self.root / 'system-pages'
        assets = json.loads((output / 'public-assets.json').read_text())
        self.assertEqual(set(assets), {'/icon.svg'})
        self.assertEqual((output / assets['/icon.svg']).read_bytes(), (self.public / 'icon.svg').read_bytes())
        self.assertIn('href="data:,"', (output / 'login.en.html').read_text())

    def test_site_language_metadata_is_normalized(self):
        for configured, expected in (('ru-RU', 'ru'), ('en', 'en'), ('fr', 'en'), ('../ru', 'en')):
            with self.subTest(configured=configured):
                document = dict.fromkeys(SHELLS, '<html></html>')
                document['_language'] = configured
                (self.public / 'wiki-system.json').write_text(json.dumps(document))
                extract_system_pages(self.root)
                self.assertEqual((self.root / 'system-pages/language.txt').read_text(), expected)

    def test_requires_exact_shell_set(self):
        (self.public / 'wiki-system.json').write_text('{}')
        with self.assertRaises(ValueError):
            extract_system_pages(self.root)


if __name__ == '__main__':
    unittest.main()
