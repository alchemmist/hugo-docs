import unittest

from fastapi import HTTPException
from content_security import validate_content


class ContentSecurityTest(unittest.TestCase):
    def test_rejects_active_html(self):
        for body in ('[bad](javascript:alert%281%29)', '![bad](data:text/html;base64,PHNjcmlwdD4=)', '<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '<a href="javascript:alert(1)">bad</a>', '<iframe src="https://example.com"></iframe>', '<div style="background:url(javascript:x)">x</div>', '<svg><script>x</script></svg>'):
            with self.subTest(body=body), self.assertRaises(HTTPException):
                validate_content(body)

    def test_accepts_code_examples_and_passive_markup(self):
        for body in ('```html\n<script>alert(1)</script>\n```', '`<iframe>`', '<details><summary>More</summary>Details</details>', '<img src="/upload-image.png" alt="Image">', '$x^2$'):
            validate_content(body)
