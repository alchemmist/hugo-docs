from html import escape
from html.parser import HTMLParser


class RootThemeParser(HTMLParser):
    def __init__(self, source, theme):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.theme = theme
        self.replacement = None

    def handle_starttag(self, tag, attrs):
        if tag != 'html' or self.replacement is not None:
            return
        line, column = self.getpos()
        start = sum(len(part) for part in self.source.splitlines(keepends=True)[:line - 1]) + column
        attributes = ''.join(' ' + name + (f'="{escape(value, quote=True)}"' if value is not None else '')
                             for name, value in attrs if name != 'data-theme')
        self.replacement = (start, start + len(self.get_starttag_text()),
                            f'<html{attributes} data-theme="{self.theme}">')


def apply_theme(source, theme='light'):
    parser = RootThemeParser(source, 'dark' if theme == 'dark' else 'light')
    for offset in range(0, len(source), 1024):
        parser.feed(source[offset:offset + 1024])
        if parser.replacement is not None:
            break
    if parser.replacement is None:
        return source
    start, end, replacement = parser.replacement
    return source[:start] + replacement + source[end:]
