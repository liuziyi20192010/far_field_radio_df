"""Compare NPZ actual/reference arrays with linear or circular error."""
import argparse
import json
import math
from pathlib import Path
import numpy as np


def compare(actual, reference, tolerance, circular=False):
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('Nonnegative finite tolerance required')
    actual, reference = np.asarray(actual, float), np.asarray(reference, float)
    if actual.shape != reference.shape or actual.size == 0:
        raise ValueError('Nonempty arrays with identical shapes required')
    finite = np.isfinite(actual) & np.isfinite(reference)
    error = actual - reference
    if circular:
        error = (error + 180) % 360 - 180
    errors = np.abs(error[finite])
    return {'count': actual.size, 'nonfinite_count': int((~finite).sum()),
            'max_abs_error': float(errors.max()) if errors.size else None,
            'rmse': float(np.sqrt(np.mean(error[finite] ** 2))) if errors.size else None,
            'tolerance': tolerance, 'circular_degrees': circular,
            'passed': bool(finite.all() and np.all(errors <= tolerance))}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('npz', help='NPZ with actual and reference arrays')
    p.add_argument('--tolerance', type=float, required=True)
    p.add_argument('--circular', action='store_true')
    p.add_argument('--output')
    a = p.parse_args()
    with np.load(a.npz, allow_pickle=False) as data:
        result = compare(data['actual'], data['reference'], a.tolerance, a.circular)
    text = json.dumps(result, indent=2)
    if a.output: Path(a.output).write_text(text + '\n', encoding='utf-8')
    print(text)
    raise SystemExit(0 if result['passed'] else 1)
