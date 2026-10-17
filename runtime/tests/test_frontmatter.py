import unittest

from frontmatter import FrontMatterError, dump, parse


class FrontMatterTests(unittest.TestCase):
    def test_unchanged_documents_roundtrip_exactly(self):
        for text in (
            '---\ntitle: "Hello"\ncustom:\n  nested: [1, 2]\n---\n\nBody\n',
            '+++\ntitle = "Hello" # keep\n[custom]\nflag = true\n+++\n\nBody\n',
            '{"title":"Hello", "custom":{"flag":true}}\n\nBody\n',
            '\ufeff---\r\ntitle: Hello\r\n---\r\n\r\nBody\r\n',
            '# No metadata\n\nBody',
        ):
            with self.subTest(text=text):
                metadata, body = parse(text)
                self.assertEqual(dump(metadata, body), text)

    def test_edit_preserves_format_and_unknown_metadata(self):
        for text, format in (
            ('---\ntitle: Hello\ncustom:\n  flag: true\n---\n\nBody', 'yaml'),
            ('+++\ntitle = "Hello"\n[custom]\nflag = true\n+++\n\nBody', 'toml'),
            ('{"title":"Hello","custom":{"flag":true}}\n\nBody', 'json'),
        ):
            with self.subTest(format=format):
                metadata, body = parse(text)
                metadata['title'] = 'Changed'
                result, result_body = parse(dump(metadata, body + '!'))
                self.assertEqual(result.format, format)
                self.assertEqual(result['title'], 'Changed')
                self.assertEqual(result['custom']['flag'], True)
                self.assertEqual(result_body, 'Body!')

    def test_nested_edit_is_not_discarded(self):
        metadata, body = parse('---\ncustom:\n  flag: true\n---\nBody')
        metadata['custom']['flag'] = False
        result, _ = parse(dump(metadata, body))
        self.assertFalse(result['custom']['flag'])

    def test_comments_preserved_when_title_changes(self):
        for text in ('---\n# keep\ntitle: old\n---\nBody', '+++\n# keep\ntitle = "old"\n+++\nBody'):
            metadata, body = parse(text)
            metadata['title'] = 'new'
            self.assertIn('# keep', dump(metadata, body))

    def test_removed_keys_stay_removed(self):
        metadata, body = parse('---\ntitle: Old\nremove: true\n---\nBody')
        del metadata['remove']
        result, _ = parse(dump(metadata, body))
        self.assertNotIn('remove', result)

    def test_invalid_front_matter_rejected(self):
        for text in ('---\ntitle: Bad\n---oops\n', '+++\ntitle =\n+++\n', '---\n- array\n---\n', '{broken}'):
            with self.subTest(text=text), self.assertRaises(FrontMatterError):
                parse(text)

    def test_plain_mapping_defaults_yaml(self):
        metadata, body = parse(dump({'title': 'New'}, 'Body'))
        self.assertEqual(metadata.format, 'yaml')
        self.assertEqual(metadata['title'], 'New')
        self.assertEqual(body, 'Body')


if __name__ == '__main__':
    unittest.main()
