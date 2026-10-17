import copy
import io
import json
import re

import tomlkit
from ruamel.yaml import YAML


class FrontMatterError(ValueError):
    pass


class Metadata(dict):
    def __init__(self, data, format, source, prefix, separator, newline):
        super().__init__(data)
        self.format = format
        self.source = source
        self.prefix = prefix
        self.separator = separator
        self.newline = newline
        self.document = data
        self.original = copy.deepcopy(dict(data))


def parse(text):
    if not isinstance(text, str):
        raise TypeError('Markdown content must be text')
    bom = '\ufeff' if text.startswith('\ufeff') else ''
    source = text[len(bom):]
    newline = '\r\n' if '\r\n' in source else '\n'
    opening = re.match(r'^(---|\+\+\+)[ \t]*(?:\r?\n|$)', source)
    try:
        if opening:
            delimiter = opening.group(1)
            closing = re.search(r'(?m)^' + re.escape(delimiter) + r'[ \t]*(?:\r?\n|$)', source[opening.end():])
            if closing is None:
                raise FrontMatterError('Missing front matter closing delimiter')
            start = opening.end()
            end = start + closing.end()
            raw = source[start:start + closing.start()]
            format = 'yaml' if delimiter == '---' else 'toml'
            if format == 'yaml':
                yaml = YAML()
                yaml.preserve_quotes = True
                data = yaml.load(raw)
                if data is None:
                    data = {}
            else:
                data = tomlkit.parse(raw)
        elif source.startswith('{'):
            data, end = json.JSONDecoder().raw_decode(source)
            format = 'json'
        else:
            return Metadata({}, 'none', bom, bom, '', newline), source
        if not isinstance(data, dict):
            raise FrontMatterError('Front matter must be a mapping')
        separator_match = re.match(r'(?:\r?\n)*', source[end:])
        separator = separator_match.group()
        body = source[end + len(separator):]
        return Metadata(data, format, bom + source[:end] + separator, bom, separator, newline), body
    except FrontMatterError:
        raise
    except Exception as error:
        raise FrontMatterError('Invalid front matter: ' + str(error)) from error


def dump(metadata, body):
    if not isinstance(body, str):
        raise TypeError('Markdown body must be text')
    if not isinstance(metadata, dict):
        raise TypeError('Front matter must be a mapping')
    if isinstance(metadata, Metadata) and metadata == metadata.original:
        return metadata.source + body
    format = getattr(metadata, 'format', 'yaml')
    if format == 'none':
        format = 'yaml'
    newline = getattr(metadata, 'newline', '\n')
    prefix = getattr(metadata, 'prefix', '')
    document = copy.deepcopy(getattr(metadata, 'document', {}))
    for key in list(document):
        if key not in metadata:
            del document[key]
    for key, value in metadata.items():
        document[key] = value
    if format == 'yaml':
        yaml = YAML()
        yaml.preserve_quotes = True
        output = io.StringIO()
        yaml.dump(document, output)
        encoded = output.getvalue().replace('\r\n', '\n').replace('\n', newline)
        header = '---' + newline + encoded + '---' + newline
    elif format == 'toml':
        encoded = tomlkit.dumps(document).replace('\r\n', '\n').replace('\n', newline)
        header = '+++' + newline + encoded.rstrip('\r\n') + newline + '+++' + newline
    elif format == 'json':
        header = json.dumps(document, ensure_ascii=False, indent=2).replace('\n', newline)
    else:
        raise FrontMatterError('Unsupported front matter format: ' + format)
    separator = getattr(metadata, 'separator', newline)
    if format == 'json' and not separator:
        separator = newline + newline
    return prefix + header + separator + body
