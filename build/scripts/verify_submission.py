"""Check engineering package; --strict additionally rejects outstanding competition evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--strict', action='store_true')
    a = p.parse_args()
    for part in ['src', 'sim', 'build', 'board', 'data', 'skill', 'report']:
        if not (ROOT / part).is_dir(): raise ValueError('Missing required directory: ' + part)
    for file in ROOT.rglob('*'):
        relative = file.relative_to(ROOT)
        if relative.as_posix().startswith('build/work/') or any(x in ['.git', '.Xil', '__pycache__'] for x in relative.parts):
            continue
        if file.is_file() and file.suffix.lower() == '.zip':
            raise ValueError('Directory delivery must not contain ZIP archives: ' + relative.as_posix())
        for component in relative.parts:
            if component in ['README.md', 'SKILL.md', '.gitignore', '.gitattributes']:
                continue
            if not re.fullmatch(r'[a-z0-9_\-]+(?:\.[a-z0-9_\-]+)*', component):
                raise ValueError('Invalid delivery name: ' + relative.as_posix())
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/check_artifacts.py')], check=True)
    marks = {'build/reports/current/build.log': ['PHASE_BUILD_PASS'],
             'build/reports/current/simulate.log': ['PHASE_RTL_PASS', 'DAC_RTL_PASS', 'CORDIC_EXHAUSTIVE_PASS'],
             'build/reports/current/check_dac_implemented.log': ['DAC_IMPLEMENTED_PASS'],
             'build/reports/current/check_dac_iob.log': ['DAC_IOB_PASS']}
    for file, expected in marks.items():
        text = (ROOT / file).read_text(encoding='utf-8', errors='replace')
        for mark in expected:
            if not re.search(r'^' + mark + r'(?:[:\s]|$)', text, flags=re.M):
                raise ValueError('Missing actual pass output: ' + mark)
    manifest = ROOT / 'submission_manifest.json'
    if manifest.exists():
        records = json.loads(manifest.read_text())
        from prepare_submission import included
        actual_files = {path.relative_to(ROOT).as_posix() for path in ROOT.rglob('*') if included(path)}
        if actual_files != set(records):
            raise ValueError('Submission file set changed; run prepare_submission.py')
        for relative, spec in records.items():
            raw = (ROOT / relative).read_bytes()
            if len(raw) != spec['bytes'] or hashlib.sha256(raw).hexdigest() != spec['sha256']:
                raise ValueError('Submission manifest mismatch: ' + relative)
    status = json.loads((ROOT / 'submission_status.json').read_text(encoding='utf-8'))
    pending = [key for key in ['board_evidence_complete', 'optimization_baseline_complete',
                              'third_party_redistribution_resolved', 'public_repository_published'] if not status[key]]
    print('ENGINEERING_PACKAGE_PASS: names, paired artifacts, actual build/simulation markers' +
          (', manifest' if manifest.exists() else ''))
    print('COMPETITION_PENDING: ' + ', '.join(pending) if pending else 'COMPETITION_STATUS_COMPLETE')
    if a.strict and pending:
        raise SystemExit(2)


if __name__ == '__main__': main()
