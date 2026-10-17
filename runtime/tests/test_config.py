import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from config import Settings


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'WIKI_CONFIG': str(self.root / 'wiki.yaml'), 'WIKI_DATA_DIR': str(self.root / 'data'), 'WIKI_BOOTSTRAP_SECRET_FILE': ''}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_fresh_defaults_generate_persistent_bootstrap_token(self):
        first = Settings.load()
        self.assertFalse(first.repository)
        self.assertTrue(first.live)
        self.assertEqual(first.content_prefix, 'content')
        self.assertGreaterEqual(len(first.bootstrap_secret), 32)
        self.assertEqual(first.bootstrap_secret, Settings.load().bootstrap_secret)
        self.assertEqual(stat.S_IMODE((first.data_dir / 'bootstrap-token').stat().st_mode), 0o600)

    def test_yaml_config_supports_subpath_and_migration_prefix(self):
        (self.root / 'wiki.yaml').write_text('url: https://wiki.example/docs/\npublic: false\nsite: /site\nstorage:\n  content_prefix: wiki/content\ngit:\n  repository: git@example:docs.git\n  branch: docs\n')
        config = Settings.load()
        self.assertEqual(config.base_path, '/docs')
        self.assertEqual(config.content_prefix, 'wiki/content')
        self.assertEqual(config.template_dir, Path('/site'))
        self.assertFalse(config.public)
        self.assertEqual(config.branch, 'docs')

    def test_environment_overrides_yaml(self):
        (self.root / 'wiki.yaml').write_text('url: https://wiki.example\npublic: false\n')
        with patch.dict(os.environ, PUBLIC_ORIGIN='http://localhost:8080/test', WIKI_PUBLIC='true'):
            config = Settings.load()
        self.assertEqual(config.base_path, '/test')
        self.assertTrue(config.public)

    def test_rejects_unsafe_prefixes(self):
        for value in ('../outside', '/absolute', 'path/../content', 'path//content', '.git', 'path\\content'):
            with self.subTest(value=value), patch.dict(os.environ, CONTENT_PREFIX=value), self.assertRaises(ValueError):
                Settings.load()
