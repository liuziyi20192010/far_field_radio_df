"""Evaluate old/new *digital DAC fundamental* phase, not ADC/board accuracy.

Read the actual ROM artifacts, model steady-state scaling, and compare the
ten physical output samples against the ideal requested phase for all 1024
phase codes. Both old and new errors subtract their own zero-phase baseline.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def signed_rom(path):
    raw = np.array([int(value, 16) for value in path.read_text(encoding='ascii').split()], dtype=np.int64)
    return np.where(raw >= 32768, raw - 65536, raw)


def wrap(value):
    return (value + 180.0) % 360.0 - 180.0


def evaluate():
    legacy_path = ROOT / 'src/rtl/sine_1024.mem'
    new_path = ROOT / 'src/rtl/sine_5120_q6.mem'
    legacy = np.array([int(value, 16) for value in legacy_path.read_text().split()], dtype=np.int64)
    physical_rom = signed_rom(new_path)
    if len(legacy) != 1024 or len(physical_rom) != 8192:
        raise ValueError('ROM dimensions do not match the DAC interfaces')
    if np.any(physical_rom[5120:]):
        raise ValueError('Unused physical ROM padding must be zero')
    rom = physical_rom[:5120]
    if not np.array_equal(rom[:2560], -rom[2560:]):
        raise ValueError('Q6 sine coefficients must be antisymmetric')
    offsets = np.arange(1024)
    index = np.arange(10)
    expected_deg = wrap(offsets * 360.0 / 1024)
    oscillator = np.exp(-2j * np.pi * index / 10)
    legacy_index = np.array([0, 102, 205, 307, 410, 512, 614, 717, 819, 922])
    results = []
    for gain in [13, 32, 64, 96, 128, 192, 256]:
        old = np.clip((((legacy[(offsets[:, None] + legacy_index) % 1024] - 512) * gain) >> 8) + 512, 0, 1023)
        product = rom[(offsets[:, None] * 5 + index * 512) % 5120] * gain
        rounded = (product + np.where(product < 0, 8191, 8192)) >> 14
        new = np.clip(rounded + 512, 0, 1023)
        row = {'gain_code': gain, 'gain': gain / 256.0}
        for label, codes in [('legacy', old), ('exact_phase_q6', new)]:
            z = codes @ oscillator
            errors = wrap(np.angle(z / z[0], deg=True) - expected_deg)
            row[label] = {'max_abs_error_deg': float(np.max(np.abs(errors))),
                          'rms_error_deg': float(np.sqrt(np.mean(errors * errors))),
                          'plus_45_error_deg': float(errors[128]),
                          'minus_45_error_deg': float(errors[896]),
                          'minimum_code': int(codes.min()), 'maximum_code': int(codes.max())}
        results.append(row)
    default = next(row for row in results if row['gain_code'] == 128)
    full = next(row for row in results if row['gain_code'] == 256)
    if default['exact_phase_q6']['max_abs_error_deg'] >= 0.13:
        raise AssertionError('Default-gain numerical bound regressed')
    if abs(default['exact_phase_q6']['plus_45_error_deg']) >= 0.01:
        raise AssertionError('Default-gain 45-degree numerical error regressed')
    if full['exact_phase_q6']['max_abs_error_deg'] >= 0.06:
        raise AssertionError('Full-gain numerical bound regressed')
    return {'evidence_type': 'offline_digital_dac_model', 'physical_dac_bits': 10,
            'dac_sample_rate_hz': 125_000_000, 'tone_hz': 12_500_000,
            'samples_per_period': 10, 'phase_codes_tested_per_gain': 1024,
            'rom_fractional_bits': 6, 'rom_phase_positions': 5120, 'rom_physical_depth': 8192,
            'rom_sha256': hashlib.sha256(new_path.read_bytes()).hexdigest(),
            'reference': 'ideal requested phase; subtract each digital generator zero-phase baseline',
            'excluded_effects': ['DAC analog response', 'reconstruction/anti-alias filters',
                                 'ADC sampling and quantization', 'board/cable delay', 'clock noise'],
            'limitations': ['Finite 10-bit output means some low-gain phase errors worsen versus the legacy generator.',
                            'No phase-specific correction fitted to user measurements is applied.',
                            'These are digital fundamental phase errors, not board measurement accuracy.'],
            'gains': results, 'status': 'DAC_NUMERIC_PASS'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = evaluate()
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
