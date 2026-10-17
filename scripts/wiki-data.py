import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


FORMAT_VERSION = 1


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def link_target(root, path):
    target = Path(os.readlink(path))
    if target.is_absolute():
        target = target.resolve()
        if not target.is_relative_to(root):
            try:
                target = root / target.relative_to('/data')
            except ValueError:
                raise ValueError(f'External absolute symlink: {path}') from None
    else:
        target = path.parent / target
    target = Path(os.path.abspath(target))
    if not target.is_relative_to(root):
        raise ValueError(f'Escaping symlink: {path}')
    return target


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = link_target(root, path)
            result[name] = {'type': 'link', 'target': target.relative_to(root).as_posix()}
        elif path.is_dir():
            result[name] = {'type': 'directory'}
        elif path.is_file():
            result[name] = {'type': 'file', 'size': path.stat().st_size, 'sha256': digest(path)}
        else:
            raise ValueError(f'Unsupported filesystem object: {path}')
    return result


def validate(root):
    if not (root / 'repository' / '.git').is_dir():
        raise ValueError('Missing repository/.git')
    current = root / 'live' / 'current'
    if not current.is_symlink():
        raise ValueError('Missing live/current publication pointer')
    target = link_target(root, current)
    if not target.is_relative_to(root / 'live' / 'snapshots'):
        raise ValueError('Publication pointer is outside snapshots')
    state = json.loads((target / 'state.json').read_text())
    states = list((root / 'live' / 'snapshots').glob('*/state.json'))
    pending = 0
    for path in states:
        record = json.loads(path.read_text())
        for field in ('commit', 'base'):
            revision = record.get(field)
            if not isinstance(revision, str) or len(revision) not in (40, 64) or any(c not in '0123456789abcdef' for c in revision):
                raise ValueError(f'Invalid {field} in {path}')
            subprocess.run(['git', '-C', str(root / 'repository'), 'cat-file', '-e', revision + '^{commit}'], check=True, capture_output=True)
        pending += bool(record.get('pending'))
    head = subprocess.run(['git', '-C', str(root / 'repository'), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    if head != state['commit']:
        raise ValueError('Repository HEAD differs from accepted publication; recover before migration')
    status = subprocess.run(['git', '-C', str(root / 'repository'), 'status', '--porcelain'], check=True, capture_output=True, text=True, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0')).stdout
    if status.strip():
        raise ValueError('Repository contains uncommitted changes; recover before migration')
    return {'commit': head, 'pending_publications': pending}


def copy_data(source, destination):
    shutil.copytree(source, destination, symlinks=True)
    for path in destination.rglob('*'):
        if path.is_symlink():
            original = source / path.relative_to(destination)
            target = destination / link_target(source, original).relative_to(source)
            path.unlink()
            path.symlink_to(os.path.relpath(target, path.parent))


def export_data(source, bundle):
    source, bundle = source.resolve(), bundle.parent.resolve() / bundle.name
    if bundle.exists() or bundle.is_symlink() or bundle.is_relative_to(source):
        raise ValueError('Bundle must be a new path outside source data')
    before = inventory(source)
    summary = validate(source)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.wiki-export-', dir=bundle.parent))
    temporary.chmod(0o700)
    try:
        copy_data(source, temporary / 'data')
        if before != inventory(source) or before != inventory(temporary / 'data'):
            raise ValueError('Source changed during export; stop all writers and retry')
        manifest = {'format': FORMAT_VERSION, 'summary': summary, 'entries': before}
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.rename(bundle)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return summary


def verify(bundle):
    bundle = bundle.resolve()
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('format') != FORMAT_VERSION:
        raise ValueError('Unsupported migration bundle format')
    if inventory(bundle / 'data') != manifest['entries']:
        raise ValueError('Backup checksum or file inventory mismatch')
    summary = validate(bundle / 'data')
    if summary != manifest['summary']:
        raise ValueError('Backup publication metadata mismatch')
    return summary


def restore(bundle, destination):
    bundle, destination = bundle.resolve(), destination.parent.resolve() / destination.name
    summary = verify(bundle)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination must not exist; never overwrite an active volume')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.wiki-restore-', dir=destination.parent))
    temporary.chmod(0o700)
    try:
        copy_data(bundle / 'data', temporary / 'data')
        if inventory(temporary / 'data') != inventory(bundle / 'data'):
            raise ValueError('Restored checksum mismatch')
        validate(temporary / 'data')
        (temporary / 'data').rename(destination)
    finally:
        shutil.rmtree(temporary)
    return summary


def main():
    parser = argparse.ArgumentParser(description='Offline backup and restore of a stopped wiki runtime data directory')
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--source', type=Path, required=True)
    export.add_argument('--bundle', type=Path, required=True)
    export.add_argument('--offline', action='store_true', required=True, help='Confirm every writer, including Git sync, is stopped')
    check = commands.add_parser('verify')
    check.add_argument('--bundle', type=Path, required=True)
    load = commands.add_parser('restore')
    load.add_argument('--bundle', type=Path, required=True)
    load.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'export':
            result = export_data(args.source, args.bundle)
        elif args.command == 'verify':
            result = verify(args.bundle)
        else:
            result = restore(args.bundle, args.destination)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Migration failed: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
