"""Deploy PS sources with a completed build or verified unchanged hardware."""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--software-only', action='store_true',
                        help='Reuse recorded hardware after verifying its hashes')
    args = parser.parse_args()
    if args.software_only:
        # Check before changing the deployed software or its immutable manifest.
        from check_artifacts import verify_software_hardware
        verify_software_hardware()
    for name in ['phase_measure.py', 'dashboard.py', 'profile_pynq.py']:
        shutil.copy2(ROOT / 'src/ps' / name, ROOT / 'board/app' / name)
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/make_notebook.py')], check=True)
    app = ROOT / 'board/app'
    for source, name in [(ROOT / 'board/README.md', 'readme.md'),
                         (ROOT / 'license', 'license'),
                         (ROOT / 'third_party_notices.md', 'third_party_notices.md')]:
        shutil.copy2(source, app / name)
    mode = '--software-only' if args.software_only else '--built'
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/check_artifacts.py'), mode, '--refresh'], check=True)
    upload = ROOT / 'far_field_radio_df'
    upload.mkdir(exist_ok=True)
    for source in app.rglob('*'):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
            continue
        target = upload / source.relative_to(app)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print('UPLOAD_FOLDER_PASS:', upload)


if __name__ == '__main__':
    main()
