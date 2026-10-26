"""Reproduce from source with an explicitly selected Vivado executable."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vivado', required=True)
    p.add_argument('--simulate-only', action='store_true')
    a = p.parse_args()
    work = ROOT / 'build/work'
    reports = ROOT / 'build/reports/current'
    work.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    def vivado(script, marker):
        log = reports / (script + '.log')
        cmd = [a.vivado, '-mode', 'batch', '-source', str(ROOT / 'build/scripts' / (script + '.tcl')),
               '-log', str(log), '-journal', str(work / (script + '.jou'))]
        subprocess.run(cmd, cwd=work, check=True)
        if marker not in log.read_text(encoding='utf-8', errors='replace'):
            raise RuntimeError('Missing completion marker: ' + marker)
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/prepare_sources.py')], check=True)
    if not a.simulate_only and not (work / 'vivado/phase_measure/phase_measure.xpr').exists():
        vivado('create_project', 'PHASE_PROJECT_PASS')
    vivado('simulate', 'CORDIC_EXHAUSTIVE_PASS')
    simlog = (reports / 'simulate.log').read_text(encoding='utf-8', errors='replace')
    if any(marker not in simlog for marker in ['PHASE_RTL_PASS', 'DAC_RTL_PASS']):
        raise RuntimeError('Missing RTL/DAC simulation pass marker')
    if a.simulate_only:
        return
    vivado('build', 'PHASE_BUILD_PASS')
    vivado('check_dac_iob', 'DAC_IOB_PASS')
    vivado('check_dac_implemented', 'DAC_IMPLEMENTED_PASS')
    tested_bit = work/'vivado/phase_measure/phase_measure.runs/impl_1/system_wrapper.bit'
    (reports/'implemented_bit.sha256').write_text(
        hashlib.sha256(tested_bit.read_bytes()).hexdigest()+'\n', encoding='ascii')
    for f in (work / 'logs').glob('*.rpt'):
        shutil.copy2(f, reports / f.name)
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/check_pinmap.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'build/scripts/deploy.py')], check=True)
    snapshot = ROOT / 'src/bd'
    snapshot.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work / 'vivado/phase_measure/phase_measure.srcs/sources_1/bd/system/system.bd', snapshot / 'system.bd')
    shutil.copy2(work / 'vivado/phase_measure/phase_measure.gen/sources_1/bd/system/hdl/system_wrapper.v', snapshot / 'system_wrapper.v')
    print('REPRODUCTION_PASS')


if __name__ == '__main__':
    main()
