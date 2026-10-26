"""Verify immutable deployment manifest. --refresh only after intentional generation."""
from pathlib import Path
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
import sys

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'board/app'
sys.path.insert(0, str(ROOT / 'skill/pynq-workflow/scripts'))
from overlay_audit import audit

names = ['phase_measure.py', 'dashboard.py', 'far_field_radio_df.ipynb',
         'overlay/far_field_radio_df.bit', 'overlay/far_field_radio_df.hwh',
         'profile_pynq.py', 'build_info.json', 'readme.md', 'license', 'third_party_notices.md']


def hardware_inputs():
    return (sorted((ROOT/'src/rtl').glob('*.v'))
            + sorted((ROOT/'src/rtl').glob('*.mem'))
            + [ROOT/'src/constraints/phase_measure.xdc'])


def file_record(path):
    return dict(bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def verify_implemented_evidence():
    """Require a real routed-netlist pass bound to this exported bitstream."""
    reports = ROOT/'build/reports/current'
    log = (reports/'check_dac_implemented.log').read_text(encoding='utf-8', errors='replace')
    if not re.search(r'^DAC_IMPLEMENTED_PASS:', log, flags=re.M):
        raise ValueError('Missing actual implemented DAC simulation pass')
    tested_sha = (reports/'implemented_bit.sha256').read_text(encoding='ascii').strip()
    if tested_sha != file_record(APP/'overlay/far_field_radio_df.bit')['sha256']:
        raise ValueError('Implemented DAC evidence does not describe the exported BIT')


def verify_software_hardware():
    """Allow a software refresh only against the recorded, unchanged hardware.

    Content hashes also work after extracting a release, whose timestamps need
    not preserve the original source/build ordering. Do not rewrite build_info:
    a software deployment is not evidence of a new hardware build or board test.
    """
    manifest = json.loads((APP/'manifest.json').read_text(encoding='utf-8'))
    for name in ('overlay/far_field_radio_df.bit',
                 'overlay/far_field_radio_df.hwh', 'build_info.json'):
        if manifest.get(name) != file_record(APP/name):
            raise ValueError('Software-only refresh requires unchanged hardware metadata/export: ' + name)
    info = json.loads((APP/'build_info.json').read_text(encoding='utf-8'))
    if info.get('bit_sha256') != manifest['overlay/far_field_radio_df.bit']['sha256']:
        raise ValueError('Build metadata does not describe the exported BIT')
    actual = {p.relative_to(ROOT).as_posix(): file_record(p)['sha256']
              for p in hardware_inputs()}
    if info.get('hardware_sources') != actual:
        raise ValueError('Hardware input set/content changed; complete a hardware build before refreshing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--built', action='store_true')
    mode.add_argument('--software-only', action='store_true',
                      help='Verify recorded hardware hashes and preserve build metadata')
    args = parser.parse_args()
    if args.refresh and not (args.built or args.software_only):
        raise ValueError('Use --refresh with --built or --software-only')
    verify_implemented_evidence()
    if args.software_only:
        verify_software_hardware()
    if args.built:
        outputs = {
            'overlay/far_field_radio_df.bit': 'phase_measure.runs/impl_1/system_wrapper.bit',
            'overlay/far_field_radio_df.hwh': 'phase_measure.gen/sources_1/bd/system/hw_handoff/system.hwh',
        }
        for deployed, generated in outputs.items():
            if (APP / deployed).read_bytes() != (ROOT / 'build/work/vivado/phase_measure' / generated).read_bytes():
                raise ValueError('Build/export mismatch: ' + deployed)
    if args.refresh and args.built:
        bit = APP / 'overlay/far_field_radio_df.bit'
        inputs = hardware_inputs()
        if any(source.stat().st_mtime_ns > bit.stat().st_mtime_ns for source in inputs):
            raise ValueError('Hardware input newer than exported BIT; rebuild before refreshing')
        reports = ROOT/'build/reports/current'
        timing = (reports/'timing_summary.rpt').read_text(encoding='utf-8', errors='replace')
        utilization = (reports/'utilization.rpt').read_text(encoding='utf-8', errors='replace')
        summary = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([\d.\-]+)\s+([\d.\-]+)\s+\d+\s+\d+\s+'
                            r'([\d.\-]+)\s+([\d.\-]+)', timing)
        if not summary:
            raise ValueError('Unrecognized timing summary; cannot record build metadata')
        wns, tns, whs, ths = map(float, summary.groups())
        if min(wns, tns, whs, ths) < 0:
            raise ValueError('Timing failed; refusing to refresh deployment metadata')
        info = dict(hardware_version='2026_10_25_dac1_reference_fix', project_name='远场模拟无线电实时测向系统',
                    metadata_recorded_utc=datetime.now(timezone.utc).isoformat(),
                    bit_sha256=hashlib.sha256(bit.read_bytes()).hexdigest(),
                    hardware_sources={p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in inputs}, wns_ns=wns, tns_ns=tns, whs_ns=whs, ths_ns=ths,
                    board_test_status='pending')
        for key, title in [('lut', 'Slice LUTs'), ('ff', 'Slice Registers'),
                           ('bram_tiles', 'Block RAM Tile'), ('dsp', 'DSPs')]:
            match = re.search(r'\|\s*' + re.escape(title) + r'\s*\|\s*([\d.]+)\s*\|', utilization)
            if not match:
                raise ValueError('Missing resource table: ' + key)
            info[key] = float(match.group(1))
        (APP/'build_info.json').write_text(json.dumps(info, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.refresh:
        manifest = {n: file_record(APP/n) for n in names}
        (APP / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    contract = json.loads((ROOT / 'board/overlay_contract.json').read_text(encoding='utf-8'))
    audit(APP / 'overlay/far_field_radio_df.bit', contract, APP / 'manifest.json')
    info = json.loads((APP/'build_info.json').read_text(encoding='utf-8'))
    if info['bit_sha256'] != hashlib.sha256((APP/'overlay/far_field_radio_df.bit').read_bytes()).hexdigest():
        raise ValueError('Build metadata does not describe the exported BIT')
    for name in ['phase_measure.py', 'dashboard.py', 'profile_pynq.py']:
        if (ROOT / 'src/ps' / name).read_bytes() != (APP / name).read_bytes():
            raise ValueError('Source/deployment mismatch: ' + name)
    print('ARTIFACTS_PASS: immutable manifest and configurable HWH contract checked')


if __name__ == '__main__':
    main()
