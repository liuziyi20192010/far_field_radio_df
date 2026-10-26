"""Prepare and verify a directory submission without generating archives."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def included(path):
    relative = path.relative_to(ROOT)
    return (path.is_file()
            and not any(part in ('__pycache__', '.git', '.Xil', '.pytest_cache')
                        for part in relative.parts)
            and not relative.as_posix().startswith('build/work/')
            and path.suffix not in ('.pyc', '.zip')
            and path.name != 'submission_manifest.json')


def main():
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/check_artifacts.py')], check=True)
    app = ROOT / 'board/app'
    deployed = ROOT / 'far_field_radio_df'
    for path in sorted(app.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            other = deployed / path.relative_to(app)
            if not other.is_file() or path.read_bytes() != other.read_bytes():
                raise ValueError('Upload folder differs from board/app: ' + str(path.relative_to(app)))
    files = sorted(path for path in ROOT.rglob('*') if included(path))
    manifest = {path.relative_to(ROOT).as_posix(): dict(
        bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in files}
    (ROOT / 'submission_manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/verify_submission.py')], check=True)
    print('DIRECTORY_SUBMISSION_PASS:', len(files), 'files;', ROOT)


if __name__ == '__main__':
    main()
