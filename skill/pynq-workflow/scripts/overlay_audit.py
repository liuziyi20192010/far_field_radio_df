"""Read-only BIT/HWH/manifest and configurable IP contract audit; Python stdlib."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def within(path, base):
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def audit(bitfile, contract, manifest=None):
    bit = Path(bitfile).resolve()
    hwh = bit.with_suffix('.hwh')
    if not bit.is_file() or not bit.stat().st_size or not hwh.is_file():
        raise ValueError('Nonempty BIT and same-stem HWH required')
    modules = {}
    for m in ET.parse(hwh).findall('.//MODULE'):
        modules[m.get('INSTANCE')] = {
            'vlnv': m.get('VLNV'),
            'parameters': {p.get('NAME'): p.get('VALUE') for p in m.findall('./PARAMETERS/PARAMETER')},
        }
    for name, spec in contract.get('ips', {}).items():
        if name not in modules:
            raise ValueError('Missing IP: ' + name)
        for parameter, expected in spec.get('parameters', {}).items():
            if modules[name]['parameters'].get(parameter) != str(expected):
                raise ValueError(f'{name}.{parameter}: expected {expected}, got '
                                 f'{modules[name]["parameters"].get(parameter)}')
    checked = []
    if manifest:
        manifest = Path(manifest).resolve()
        base = manifest.parent
        entries = json.loads(manifest.read_text(encoding='utf-8'))
        for relative, expected in entries.items():
            p = (base / relative).resolve()
            if not within(p, base):
                raise ValueError('Manifest path escapes package: ' + relative)
            raw = p.read_bytes()
            if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                raise ValueError('Manifest mismatch: ' + relative)
            checked.append(relative)
        for p in [bit, hwh]:
            if not within(p, base) or p.relative_to(base).as_posix() not in checked:
                raise ValueError('Manifest must cover BIT and HWH')
    return {'status': 'pass', 'scope': 'metadata_and_hashes_only',
            'ips': modules, 'manifest_files_checked': checked}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bit', required=True)
    parser.add_argument('--contract', required=True)
    parser.add_argument('--manifest')
    args = parser.parse_args()
    print(json.dumps(audit(args.bit, json.loads(Path(args.contract).read_text(encoding='utf-8')),
                           args.manifest), indent=2))
