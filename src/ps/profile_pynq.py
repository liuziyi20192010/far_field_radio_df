"""Record board capture timings and unsmoothed phase evidence without a GUI.

Close the Dashboard and other DMA users before running this tool. It creates a
new Overlay session with DAC output disabled. Only --dac-phase enables its DAC.
CSV/NPZ compression occurs after capture so disk writes do not inflate each
capture timing. This tool measures capture/optional FFT, not browser FPS.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np


HERE = Path(__file__).resolve().parent
# Same script works in src/ps, board/app and a flat deployment ZIP.
if HERE.name == 'ps' and HERE.parent.name == 'src':
    ROOT = HERE.parent.parent
    APP = ROOT / 'board/app'
else:
    APP = HERE
    ROOT = HERE.parent.parent if HERE.name == 'app' and HERE.parent.name == 'board' else HERE
TIMING_STAGES = ('prepare', 'allocate', 'dma', 'copy', 'decode', 'total')
ROW_FIELDS = (
    'index', 'timestamp_utc', 'sequence', 'flags', 'valid', 'pipeline_consistent',
    'overrange', 'test_mode', 'reference_deg', 'raw_phase_deg',
    'calibrated_phase_deg', 'software_phase_deg', 'pl_software_error_deg',
    'reference_error_deg', 'amplitude_ch1_codes', 'amplitude_ch2_codes',
    'capture_wall_ms', 'fft_ms', 'host_loop_ms',
) + tuple('capture_' + stage + '_ms' for stage in TIMING_STAGES)


def wrap_degrees(value):
    return (value + 180.0) % 360.0 - 180.0


def circular_summary(values):
    """Population spread around the circular mean, rejecting nonfinite inputs."""
    values = np.asarray(values, dtype=float)
    if values.ndim != 1:
        raise ValueError('Expected a one-dimensional angle sequence')
    finite = values[np.isfinite(values)]
    summary = {'count': int(finite.size), 'nonfinite_count': int(values.size - finite.size),
               'mean_deg': None, 'std_deg': None, 'peak_to_peak_deg': None,
               'unwrapped_min_deg': None, 'unwrapped_max_deg': None,
               'resultant_length': None}
    if not finite.size:
        return summary
    vector = np.mean(np.exp(1j * np.deg2rad(finite)))
    concentration = float(abs(vector))
    summary['resultant_length'] = concentration
    if concentration < 1e-12:
        return summary  # a nearly cancelling circular distribution has no useful mean
    mean = wrap_degrees(float(np.angle(vector, deg=True)))
    residual = (finite - mean + 180.0) % 360.0 - 180.0
    summary.update(mean_deg=mean, std_deg=float(np.std(residual)),
                   peak_to_peak_deg=float(np.ptp(residual)),
                   unwrapped_min_deg=mean + float(residual.min()),
                   unwrapped_max_deg=mean + float(residual.max()))
    return summary


def scalar_summary(values):
    values = np.asarray(values, dtype=float)
    finite = values[np.isfinite(values)]
    if not finite.size:
        return {'count': 0, 'median': None, 'p95': None, 'maximum': None}
    return {'count': int(finite.size), 'median': float(np.median(finite)),
            'p95': float(np.percentile(finite, 95)), 'maximum': float(finite.max())}


def verify_manifest(path, bitfile):
    """Read-only check; do not regenerate a manifest when verifying old files."""
    path, bitfile = Path(path).resolve(), Path(bitfile).resolve()
    base = path.parent
    entries = json.loads(path.read_text(encoding='utf-8'))
    checked = []
    for relative, expected in entries.items():
        file = (base / relative).resolve()
        try:
            file.relative_to(base)
        except ValueError:
            raise ValueError('Manifest path escapes deployment directory: ' + relative)
        raw = file.read_bytes()
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('Manifest mismatch: ' + relative)
        checked.append(file)
    if bitfile not in checked or bitfile.with_suffix('.hwh') not in checked:
        raise ValueError('Manifest must cover the selected BIT and same-stem HWH')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_frames(instrument, frames, reference_deg=None, timeout=2.0,
                   period_s=0.0, fft_function=None, rows=None, words=None):
    """Collect one physical DMA serially; retain partial evidence if interrupted.

    A caller can supply rows/words lists to receive frames completed before an
    exception. Neither raw nor calibrated phase is smoothed or corrected here.
    """
    if not isinstance(frames, int) or frames < 1:
        raise ValueError('frames must be a positive integer')
    if reference_deg is not None and not math.isfinite(reference_deg):
        raise ValueError('reference_deg must be finite when supplied')
    if not math.isfinite(period_s) or period_s < 0:
        raise ValueError('period_s must be nonnegative and finite')
    rows = [] if rows is None else rows
    words = [] if words is None else words
    for index in range(frames):
        started = time.perf_counter()
        frame = instrument.capture(timeout=timeout, reuse_buffer=True)
        captured = time.perf_counter()
        if fft_function is not None:
            fft_function(frame['samples'])
        fft_done = time.perf_counter()
        valid = bool(frame['valid'])
        consistent = bool(frame['pipeline_consistent'])
        calibrated = float(frame['calibrated_phase_deg'])
        row = {
            'index': index, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'sequence': int(frame['sequence']), 'flags': int(frame['flags']),
            'valid': valid, 'pipeline_consistent': consistent,
            'overrange': bool(frame['overrange']), 'test_mode': bool(frame['test_mode']),
            'reference_deg': '' if reference_deg is None else float(reference_deg),
            'raw_phase_deg': float(frame['raw_phase_deg']),
            'calibrated_phase_deg': calibrated,
            'software_phase_deg': float(frame['software_phase_deg']),
            'pl_software_error_deg': wrap_degrees(float(frame['raw_phase_deg']) - float(frame['software_phase_deg'])),
            'reference_error_deg': (wrap_degrees(calibrated - reference_deg)
                                    if reference_deg is not None and valid and consistent else float('nan')),
            'amplitude_ch1_codes': float(frame['amplitude'][0]),
            'amplitude_ch2_codes': float(frame['amplitude'][1]),
            'capture_wall_ms': (captured - started) * 1000.0,
            'fft_ms': (fft_done - captured) * 1000.0 if fft_function is not None else 0.0,
        }
        timing = frame.get('timings_ms', {})
        row.update({'capture_' + stage + '_ms': float(timing.get(stage, float('nan')))
                    for stage in TIMING_STAGES})
        # Copy now: a later capture or an injected test backend must not change evidence.
        words.append(np.asarray(frame['words'], dtype=np.uint32).copy())
        row['host_loop_ms'] = (time.perf_counter() - started) * 1000.0
        rows.append(row)
        remaining = period_s - (time.perf_counter() - started)
        if remaining > 0:
            time.sleep(remaining)
    return rows, words


def summarize_rows(rows):
    accepted = [r for r in rows if r['valid'] and r['pipeline_consistent']]
    fields = ('capture_wall_ms', 'fft_ms', 'host_loop_ms') + tuple(
        'capture_' + stage + '_ms' for stage in TIMING_STAGES)
    return {
        'frames_recorded': len(rows), 'valid_consistent_frames': len(accepted),
        'invalid_or_inconsistent_frames': len(rows) - len(accepted),
        'phase_raw_deg': circular_summary([r['raw_phase_deg'] for r in accepted]),
        'phase_calibrated_deg': circular_summary([r['calibrated_phase_deg'] for r in accepted]),
        'reference_error_deg': circular_summary([r['reference_error_deg'] for r in accepted]),
        'pl_software_error_deg': circular_summary([r['pl_software_error_deg'] for r in accepted]),
        'timings_ms': {field: scalar_summary([r[field] for r in rows]) for field in fields},
        'amplitude_ch1_codes': scalar_summary([r['amplitude_ch1_codes'] for r in accepted]),
        'amplitude_ch2_codes': scalar_summary([r['amplitude_ch2_codes'] for r in accepted]),
        'statistics_note': 'Population standard deviation about circular mean; invalid frames retained in raw evidence but excluded from accuracy statistics.',
    }


def write_run(output, rows, words, metadata):
    output = Path(output)
    if len(rows) != len(words):
        raise ValueError('Every CSV row must have one matching raw packet')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    with (output / 'frames.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    raw = np.stack(words) if words else np.empty((0, 0), dtype=np.uint32)
    np.savez_compressed(output / 'raw_frames.npz', words=raw,
                        sequence=np.array([r['sequence'] for r in rows], dtype=np.uint32))
    summary = summarize_rows(rows)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--frames', type=int, default=200)
    p.add_argument('--bit', default=str(APP / 'overlay/far_field_radio_df.bit'))
    p.add_argument('--encoding', choices=['offset_binary', 'twos_complement'], default='offset_binary')
    p.add_argument('--timeout', type=float, default=2.0)
    p.add_argument('--period', type=float, default=0.0, help='Minimum seconds between captures; 0 measures available capture throughput')
    p.add_argument('--fft', action='store_true', help='Also compute FFT once per capture, without drawing it')
    p.add_argument('--reference-deg', type=float, help='Known external CH2-CH1 phase, used only for comparison')
    p.add_argument('--dac-phase', type=float, help='Explicitly enable board DAC at this phase; omitted means DAC stays off')
    p.add_argument('--gain', type=float, help='DAC gain, only valid with --dac-phase; default 0.5 when DAC requested')
    zero = p.add_mutually_exclusive_group()
    zero.add_argument('--zero-ready', action='store_true', help='Calibrate physically known equal-phase inputs before collecting; DAC mode first applies zero phase')
    zero.add_argument('--zero-offset-deg', type=float, help='Use a previously measured zero offset; default is no zero correction')
    p.add_argument('--calibration-frames', type=int, default=32)
    p.add_argument('--verify-manifest', action='store_true')
    p.add_argument('--manifest', default=str(APP / 'manifest.json'))
    p.add_argument('--output', help='New output directory; existing directories are never overwritten')
    return p


def main(argv=None):
    p = parser()
    a = p.parse_args(argv)
    if a.frames < 1 or a.calibration_frames < 1:
        p.error('frames and calibration-frames must be positive')
    for name in ('timeout', 'period', 'reference_deg', 'dac_phase', 'gain', 'zero_offset_deg'):
        value = getattr(a, name)
        if value is not None and not math.isfinite(value):
            p.error(name.replace('_', '-') + ' must be finite')
    if a.timeout <= 0 or a.period < 0:
        p.error('timeout must be positive and period nonnegative')
    if a.gain is not None and a.dac_phase is None:
        p.error('--gain requires --dac-phase; no implicit DAC enable')
    if a.dac_phase is not None and a.reference_deg is not None:
        p.error('Use DAC quantized setting as its reference; --reference-deg is for external input')
    gain = 0.5 if a.gain is None else a.gain
    if not 0 <= gain <= 1:
        p.error('gain must be in 0..1')
    output = Path(a.output) if a.output else ROOT / 'board/results/pynq_profile' / datetime.now(timezone.utc).strftime('run_%Y%m%d_%H%M%S_%f_utc')
    if output.exists():
        p.error('output directory already exists')
    manifest_hash = verify_manifest(a.manifest, a.bit) if a.verify_manifest else None
    # Lazy imports keep --help and pure-statistics tests independent of PYNQ.
    sys.path.insert(0, str(APP))
    from phase_measure import PhaseMeasure, spectrum
    print('Use a single DMA owner: close the Dashboard before this tool. A new Overlay is loaded; DAC starts disabled.')
    instrument = None
    rows, words = [], []
    metadata = {'evidence_type': 'board_measurement', 'status': 'incomplete',
                'created_utc': datetime.now(timezone.utc).isoformat(),
                'python': platform.python_version(), 'numpy': np.__version__,
                'bitfile': str(Path(a.bit).resolve()), 'encoding': a.encoding,
                'requested_frames': a.frames, 'fft_enabled': a.fft,
                'period_s': a.period, 'manifest_sha256': manifest_hash,
                'mode': 'board_dac' if a.dac_phase is not None else 'external_dac_off',
                'measurement_scope': 'Serial DMA capture and optional FFT; no GUI, browser, or file-compression time in per-frame timings.'}
    status = 0
    try:
        instrument = PhaseMeasure(a.bit, a.encoding)
        import pynq
        metadata['pynq_version'] = getattr(pynq, '__version__', 'not_reported')
        if a.zero_ready:
            if a.dac_phase is not None:
                instrument.set_dac(0.0, gain, True)
            instrument.calibrate_zero(frames=a.calibration_frames)
            metadata['calibration_kind'] = 'known_equal_phase_inputs'
            if a.dac_phase is None and a.reference_deg is not None and abs(wrap_degrees(a.reference_deg)) > 1e-12:
                input('Zero calibration complete. Set the external generator to CH2-CH1={:+g} degrees, let it settle, then press Enter: '.format(a.reference_deg))
        else:
            instrument.phase_zero_deg = 0.0 if a.zero_offset_deg is None else a.zero_offset_deg
            metadata['calibration_kind'] = 'supplied_offset' if a.zero_offset_deg is not None else 'none'
        metadata['zero_offset_deg'] = float(instrument.phase_zero_deg)
        reference = a.reference_deg
        if a.dac_phase is not None:
            setting = instrument.set_dac(a.dac_phase, gain, True)
            metadata['dac_setting'] = setting
            reference = float(setting['phase_deg'])
        metadata['reference_deg'] = reference
        started = time.perf_counter()
        collect_frames(instrument, a.frames, reference, a.timeout, a.period,
                       spectrum if a.fft else None, rows=rows, words=words)
        metadata['capture_session_s'] = time.perf_counter() - started
        metadata['status'] = 'complete'
    except KeyboardInterrupt:
        metadata['error'] = 'KeyboardInterrupt; completed frames retained'
        status = 130
    except Exception as exc:
        metadata['error'] = type(exc).__name__ + ': ' + str(exc)
        status = 1
    finally:
        if instrument is not None:
            try:
                instrument.close()  # driver owns reset-before-free on a failed DMA
            except Exception as exc:
                metadata['shutdown_error'] = type(exc).__name__ + ': ' + str(exc)
                metadata['status'] = 'incomplete'
                status = status or 1
        summary = write_run(output, rows, words, metadata)
    print(str(output.resolve()))
    print(json.dumps(summary, indent=2, allow_nan=False))
    return status


if __name__ == '__main__':
    raise SystemExit(main())
