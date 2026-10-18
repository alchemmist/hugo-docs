import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from ruamel.yaml import YAML

parser = argparse.ArgumentParser()
parser.add_argument('--helm', default='helm')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
binary = bytes(range(256))
binary_path = 'fonts/test.woff2'
binary_key = hashlib.sha256(binary_path.encode()).hexdigest()
logo = '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n'
with tempfile.TemporaryDirectory() as directory:
    values = Path(directory) / 'values.json'
    base = {'bootstrapSecret': 'bootstrap', 'publicURL': 'https://wiki.example/docs', 'contentPrefix': 'wiki/content'}
    values.write_text(json.dumps({**base, 'staticFiles': {'images/team.svg': logo}, 'staticBinaryFiles': {binary_path: base64.b64encode(binary).decode()}}))
    command = [args.helm, 'template', 'check', str(root / 'charts/wiki'), '-f', str(values)]
    output = subprocess.check_output(command, text=True)
    resources = list(YAML(typ='safe').load_all(output))
    config = next(item for item in resources if item['kind'] == 'ConfigMap' and 'wiki.yaml' in item.get('data', {}))
    assert YAML(typ='safe').load(config['data']['wiki.yaml'])['mcp']['enabled'] is False
    static = next(item for item in resources if item['kind'] == 'ConfigMap' and item['metadata']['name'].endswith('-static'))
    key = hashlib.sha256(b'images/team.svg').hexdigest()
    assert static['data'][key] == logo
    assert base64.b64decode(static['binaryData'][binary_key]) == binary
    deployment = next(item for item in resources if item['kind'] == 'Deployment')
    labels = deployment['spec']['template']['metadata']['labels']
    assert labels['app.kubernetes.io/name'] == 'hugo-docs-wiki'
    assert labels['app.kubernetes.io/name'] != 'wiki'
    service = next(item for item in resources if item['kind'] == 'Service')
    assert service['spec']['selector'] == labels
    assert deployment['spec']['selector']['matchLabels'] == labels
    spec = deployment['spec']['template']['spec']
    volume = next(item for item in spec['volumes'] if item['name'] == 'static')
    assert {item['path']: item['key'] for item in volume['configMap']['items']} == {'images/team.svg': key, binary_path: binary_key}
    mounts = [item for item in spec['containers'][0]['volumeMounts'] if item['name'] == 'static']
    assert len(mounts) == 2
    for mount in mounts:
        assert mount == {'name': 'static', 'mountPath': '/opt/wiki/static/' + mount['subPath'], 'subPath': mount['subPath'], 'readOnly': True}
    site = Path(directory) / 'site'
    source = site / 'static'
    projected = source / '..data' / 'images'
    projected.mkdir(parents=True)
    (projected / 'team.svg').write_text(logo)
    (source / '..data/fonts').mkdir()
    (source / '..data' / binary_path).write_bytes(binary)
    (source / 'images').symlink_to('..data/images')
    (site / 'hugo.toml').write_text("baseURL = 'https://wiki.example/'\n")
    output = Path(directory) / 'public'
    hugo = ['hugo', '--source', str(site), '--destination', str(output), '--quiet']
    subprocess.run(hugo, check=True, capture_output=True)
    assert not (output / 'images/team.svg').exists()
    (source / 'images').unlink()
    for mount in mounts:
        destination = source / Path(mount['mountPath']).relative_to('/opt/wiki/static')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / '..data' / mount['subPath'], destination)
    subprocess.run(hugo, check=True, capture_output=True)
    assert (output / 'images/team.svg').read_text() == logo
    assert (output / binary_path).read_bytes() == binary
    for invalid in ['../logo.svg', '/logo.svg', 'images/../../logo.svg', 'images//logo.svg', 'images\\logo.svg', '.hidden/logo.svg']:
        for field in ['staticFiles', 'staticBinaryFiles']:
            values.write_text(json.dumps({**base, field: {invalid: 'YQ=='}}))
            result = subprocess.run(command, capture_output=True, text=True)
            assert result.returncode != 0, (field, invalid)
    values.write_text(json.dumps({**base, 'config': {'mcp': {'enabled': True}}}))
    enabled_resources = list(YAML(typ='safe').load_all(subprocess.check_output(command, text=True)))
    enabled_config = next(item for item in enabled_resources if item['kind'] == 'ConfigMap' and 'wiki.yaml' in item.get('data', {}))
    assert YAML(typ='safe').load(enabled_config['data']['wiki.yaml'])['mcp']['enabled'] is True
    for invalid_values in [
        {'config': {'mcp': {'enabled': 'false'}}},
        {'config': {'mcp': {'enabled': 1}}},
        {'config': {'mcp': {'enable': True}}},
        {'staticBinaryFiles': {binary_path: 'not base64'}},
        {'staticBinaryFiles': {binary_path: 'ZE=='}},
        {'staticFiles': {binary_path: logo}, 'staticBinaryFiles': {binary_path: 'YQ=='}},
    ]:
        values.write_text(json.dumps({**base, **invalid_values}))
        assert subprocess.run(command, capture_output=True).returncode != 0
    values.write_text(json.dumps({**base, 'staticBinaryFiles': {binary_path: 'YQ=='}}))
    assert subprocess.run(command, capture_output=True).returncode == 0
print('Wiki chart checks passed: static asset mapping, Hugo ConfigMap projection regression and unsafe-path rejection')
