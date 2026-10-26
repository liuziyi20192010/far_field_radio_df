"""Run on the actual board after wiring/level checks; never generates mock measurements."""
import argparse
import csv
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'board/app'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / 'skill/pynq-workflow/scripts'))
from phase_measure import PhaseMeasure, wrap_degrees, signed_word
from overlay_audit import audit


def software_reference(samples, sample_rate_hz=50_000_000, frequency_hz=12_500_000):
    oscillator = np.exp(-2j * np.pi * frequency_hz * np.arange(len(samples)) / sample_rate_hz)
    z = np.asarray(samples).T @ oscillator
    return wrap_degrees(float(np.angle(z[1] * np.conj(z[0]), deg=True)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['dac', 'external'], required=True)
    p.add_argument('--zero-ready', action='store_true', help='Both real inputs are physically at zero phase for calibration')
    p.add_argument('--reference-deg', type=float, default=0, help='External generator phase set AFTER calibration')
    p.add_argument('--frames', type=int, default=20)
    p.add_argument('--gain', type=float, default=0.5)
    p.add_argument('--encoding', choices=['offset_binary', 'twos_complement'], default='offset_binary')
    p.add_argument('--output', default=str(ROOT / 'board/results' / datetime.now(timezone.utc).strftime('run_%Y%m%d_%H%M%S')))
    a = p.parse_args()
    if not a.zero_ready or a.frames < 1 or not np.isfinite(a.reference_deg):
        p.error('Prepare known equal-phase inputs, pass --zero-ready, and use positive frames/finite reference')
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=False)
    contract = json.loads((ROOT / 'board/overlay_contract.json').read_text(encoding='utf-8'))
    audit(APP / 'overlay/far_field_radio_df.bit', contract, APP / 'manifest.json')
    import pynq
    pm = PhaseMeasure(str(APP / 'overlay/far_field_radio_df.bit'), a.encoding)
    rows = []
    try:
        assert pm.test_link()
        if a.mode == 'dac': pm.set_dac(0, a.gain, True)
        else: pm.stop_dac()
        zero = pm.calibrate_zero()
        if a.mode == 'external':
            input(f'校正完成。把外部信号源 CH2-CH1 设置为 {a.reference_deg} 度并稳定后按回车：')
        phases = [0, 30, 45, 90, -45, -90, 179] if a.mode == 'dac' else [a.reference_deg]
        for requested in phases:
            setting = pm.set_dac(requested, a.gain, True) if a.mode == 'dac' else {'phase_deg': requested}
            for index in range(a.frames):
                start = time.perf_counter()
                frame = pm.capture(reuse_buffer=True)
                capture_s = time.perf_counter() - start
                start = time.perf_counter()
                baseline = software_reference(frame['samples'])
                cpu_dft_s = time.perf_counter() - start
                start = time.perf_counter()
                converted = signed_word(frame['words'][4]) * 180.0 / (1 << 31)
                pl_decode_s = time.perf_counter() - start
                row = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'mode': a.mode,
                       'requested_deg': requested, 'reference_deg': setting['phase_deg'],
                       'index': index, 'sequence': frame['sequence'], 'flags': frame['flags'],
                       'valid': frame['valid'], 'pipeline_consistent': frame['pipeline_consistent'],
                       'raw_pl_deg': frame['raw_phase_deg'], 'software_deg': baseline,
                       'calibrated_deg': frame['calibrated_phase_deg'],
                       'reference_error_deg': wrap_degrees(frame['calibrated_phase_deg'] - setting['phase_deg']),
                       'pl_software_error_deg': wrap_degrees(converted - baseline),
                       'capture_s': capture_s, 'cpu_dft_s': cpu_dft_s, 'pl_word_decode_s': pl_decode_s,
                       'amplitude_ch1_codes': frame['amplitude'][0], 'amplitude_ch2_codes': frame['amplitude'][1]}
                rows.append(row)
                np.savez_compressed(out / f'frame_{len(rows):04d}.npz', words=frame['words'], samples=frame['samples'],
                                    actual=np.array([frame['raw_phase_deg']]), reference=np.array([baseline]))
                with (out / 'measurements.csv').open('w', newline='', encoding='utf-8') as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
        meta = {'evidence_type': 'board_measurement', 'board_model': 'alientek_navigator_zynq7020',
                'part': 'xc7z020clg400-2', 'image': 'ZYNQ-7020-2.7.0.img', 'pynq_version': pynq.__version__,
                'python': platform.python_version(), 'numpy': np.__version__, 'encoding': a.encoding,
                'zero_deg': zero, 'mode': a.mode, 'manifest': json.loads((APP / 'manifest.json').read_text()),
                'frames': len(rows), 'all_valid': all(r['valid'] for r in rows),
                'all_pipeline_consistent': all(r['pipeline_consistent'] for r in rows),
                'capture_time_note': 'Includes DMA, allocation and decoder DFT; not pure PL latency.',
                'benchmark_note': 'CPU DFT time versus PL word conversion time is a host workload comparison, not total speedup.'}
        (out / 'metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        print(out)
    finally:
        pm.close()


if __name__ == '__main__': main()
