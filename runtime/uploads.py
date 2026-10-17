import base64
import binascii
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import HTTPException
from fastapi.responses import FileResponse

MAX_UPLOAD = 8 * 1024 * 1024
TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp', '.mp4': 'video/mp4', '.webm': 'video/webm', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg', '.wav': 'audio/wav', '.pdf': 'application/pdf'}


class UploadStore:
    def __init__(self, root, public_url):
        self.root = Path(root)
        self.public_url = public_url

    def checked(self, identifier, owner):
        if not isinstance(identifier, str) or not re.fullmatch(r'upload-[a-f0-9]{32}\.[a-z0-9]+', identifier):
            raise HTTPException(422, 'Invalid upload identifier')
        path = self.root / identifier
        metadata = path.with_suffix(path.suffix + '.json')
        if not path.is_file() or not metadata.is_file() or path.is_symlink() or metadata.is_symlink():
            raise HTTPException(404, 'Upload not found')
        record = json.loads(metadata.read_text())
        if record['owner'] != owner:
            raise HTTPException(403, 'Upload belongs to another editor')
        return path

    def stage(self, data, owner):
        name, encoded = data.get('name'), data.get('content')
        if not isinstance(name, str) or not isinstance(encoded, str) or len(encoded) > (MAX_UPLOAD + 2) // 3 * 4:
            raise HTTPException(422, 'Provide a filename and at most 8 MiB of base64 data')
        suffix = Path(name).suffix.lower()
        if suffix not in TYPES:
            raise HTTPException(422, 'Unsupported attachment type')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise HTTPException(422, 'Invalid base64 upload') from error
        if not content or len(content) > MAX_UPLOAD or not valid_signature(suffix, content):
            raise HTTPException(422, 'File content does not match its supported type')
        self.root.mkdir(parents=True, exist_ok=True)
        identifier = 'upload-' + secrets.token_hex(16) + suffix
        path = self.root / identifier
        with path.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        metadata = path.with_suffix(suffix + '.json')
        with metadata.open('x') as stream:
            json.dump({'owner': owner, 'name': name}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {'id': identifier, 'url': self.public_url + '/' + identifier, 'name': name}

    def preview(self, identifier, owner):
        path = self.checked(identifier, owner)
        return FileResponse(path, media_type=TYPES[path.suffix], headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "sandbox; default-src 'none'"})


def valid_signature(suffix, content):
    if suffix == '.png':
        return content.startswith(b'\x89PNG\r\n\x1a\n')
    if suffix in ('.jpg', '.jpeg'):
        return content.startswith(b'\xff\xd8\xff')
    if suffix == '.gif':
        return content.startswith((b'GIF87a', b'GIF89a'))
    if suffix == '.webp':
        return content.startswith(b'RIFF') and content[8:12] == b'WEBP'
    if suffix == '.wav':
        return content.startswith(b'RIFF') and content[8:12] == b'WAVE'
    if suffix == '.mp4':
        return content[4:8] == b'ftyp'
    if suffix == '.webm':
        return content.startswith(b'\x1aE\xdf\xa3')
    if suffix == '.mp3':
        return content.startswith(b'ID3') or (len(content) > 1 and content[0] == 255 and content[1] & 224 == 224)
    if suffix == '.ogg':
        return content.startswith(b'OggS')
    return suffix == '.pdf' and content.startswith(b'%PDF-')
