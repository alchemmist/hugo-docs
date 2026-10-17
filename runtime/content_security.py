from html.parser import HTMLParser
from urllib.parse import urlsplit

from fastapi import HTTPException
from markdown_it import MarkdownIt

ALLOWED_TAGS = frozenset('a abbr b blockquote br caption code col colgroup dd del details div dl dt em figcaption figure h1 h2 h3 h4 h5 h6 hr i img kbd li mark ol p picture pre s samp small source span strong sub summary sup table tbody td th thead tr u ul video audio'.split())
URL_ATTRIBUTES = frozenset(('href', 'src', 'poster', 'cite'))


class SafeHTML(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            raise HTTPException(422, 'Active HTML is not allowed in wiki content')
        for name, value in attrs:
            if name.startswith('on') or name in ('style', 'srcdoc', 'srcset', 'formaction', 'action', 'xmlns', 'is'):
                raise HTTPException(422, 'Active HTML attributes are not allowed')
            if name in URL_ATTRIBUTES and value:
                validate_url(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in ALLOWED_TAGS:
            raise HTTPException(422, 'Active HTML is not allowed in wiki content')


def validate_url(value):
    normalized = ''.join(character for character in value if ord(character) > 32)
    if urlsplit(normalized).scheme.lower() not in ('', 'http', 'https', 'mailto', 'tel'):
        raise HTTPException(422, 'Unsafe content URL')


def validate_content(body):
    renderer = MarkdownIt('commonmark', {'html': True})
    renderer.validateLink = lambda value: True
    for token in renderer.parse(body):
        for item in [token, *(token.children or [])]:
            for attribute in ('href', 'src'):
                if item.attrGet(attribute):
                    validate_url(item.attrGet(attribute))
            if item.type in ('html_inline', 'html_block'):
                parser = SafeHTML(convert_charrefs=True)
                parser.feed(item.content)
                parser.close()
