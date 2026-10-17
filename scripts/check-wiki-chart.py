import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from ruamel.yaml import YAML

parser = argparse.ArgumentParser()
parser.add_argument('--helm', default='helm')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
logo = '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n'
with tempfile.TemporaryDirectory() as directory:
    values = Path(directory) / 'values.json'
    base = {'bootstrapSecret': 'bootstrap', 'publicURL': 'https://wiki.example/docs', 'contentPrefix': 'wiki/content'}
    values.write_text(json.dumps({**base, 'staticFiles': {'images/team.svg': logo}}))
    command = [args.helm, 'template', 'check', str(root / 'charts/wiki'), '-f', str(values)]
    output = subprocess.check_output(command, text=True)
    resources = list(YAML(typ='safe').load_all(output))
    static = next(item for item in resources if item['kind'] == 'ConfigMap' and item['metadata']['name'].endswith('-static'))
    key = hashlib.sha256(b'images/team.svg').hexdigest()
    assert static['data'][key] == logo
    deployment = next(item for item in resources if item['kind'] == 'Deployment')
    labels = deployment['spec']['template']['metadata']['labels']
    assert labels['app.kubernetes.io/name'] == 'hugo-docs-wiki'
    assert labels['app.kubernetes.io/name'] != 'wiki'
    service = next(item for item in resources if item['kind'] == 'Service')
    assert service['spec']['selector'] == labels
    assert deployment['spec']['selector']['matchLabels'] == labels
    spec = deployment['spec']['template']['spec']
    volume = next(item for item in spec['volumes'] if item['name'] == 'static')
    assert volume['configMap']['items'] == [{'key': key, 'path': 'images/team.svg'}]
    assert any(item['mountPath'] == '/opt/wiki/static' and item['readOnly'] for item in spec['containers'][0]['volumeMounts'])
    for invalid in ['../logo.svg', '/logo.svg', 'images/../../logo.svg', 'images//logo.svg', 'images\\logo.svg', '.hidden/logo.svg']:
        values.write_text(json.dumps({**base, 'staticFiles': {invalid: logo}}))
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode != 0, invalid
print('Wiki chart checks passed: static asset mapping and unsafe-path rejection')
