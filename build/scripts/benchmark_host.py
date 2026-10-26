"""Reproducible offline CPU/HTML comparison; never a board-FPS measurement."""
import argparse
import importlib
import json
from pathlib import Path
import statistics
import sys
import time
import types
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def load_source(name, source):
    module = types.ModuleType(name)
    module.__file__ = str(ROOT / 'board/app' / (name + '.py'))
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def median_ms(function, repeats=100):
    function()
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        samples.append(1000 * (time.perf_counter() - start))
    return statistics.median(samples)


def run(baseline):
    sys.path.insert(0, str(ROOT / 'board/app'))
    sys.path.insert(0, str(ROOT / 'sim'))
    # Mock widgets isolate Python work and changed HTML payload. Real notebook
    # comm serialization, browser layout and physical DMA are deliberately absent.
    fixtures = importlib.import_module('test_dashboard')
    current = importlib.import_module('phase_measure')
    new_view = importlib.import_module('dashboard')
    previous = load_source('baseline_phase', (baseline/'notebook/phase_measure.py').read_text(encoding='utf-8'))
    with patch.dict(sys.modules, {'phase_measure': previous}):
        old_view = load_source('baseline_dashboard', (baseline/'notebook/dashboard.py').read_text(encoding='utf-8'))
    packet = importlib.import_module('test_driver').packet()
    frame = current.decode_frame(packet)
    frame['calibrated_phase_deg'] = frame['phase_deg']
    frequency, dbfs = current.spectrum(frame['samples'])
    peaks = [12_500_000, 12_500_000]
    old_ui = old_view.Dashboard(fixtures.Instrument())
    new_ui = new_view.Dashboard(fixtures.Instrument())
    payloads, render_ms = [], []
    for label, view, ui, widgets in [
        ('baseline', old_view, old_ui, ['metric_cards', 'dac_metrics', 'out', 'message']),
        ('optimized', new_view, new_ui, ['metric_cards', 'spectrum_out', 'history_out', 'model_out', 'message']),
    ]:
        changed_bytes, timings = 0, []
        for index in range(60):
            frame['sequence'] = index + 1
            before = [getattr(ui, name).value for name in widgets]
            with patch.object(view.time, 'monotonic', return_value=1.0 + index / 20.0):
                started = time.perf_counter()
                if label == 'optimized':
                    ui._update_spectrum(frame, 1.0 + index / 20.0)
                ui._render(frame, frequency, dbfs, frame['phase_deg'], 30.0, 0.01)
                timings.append(1000 * (time.perf_counter() - started))
            for name, old in zip(widgets, before):
                text = getattr(ui, name).value
                if text != old:
                    changed_bytes += len(text.encode('utf-8'))
        payloads.append((label, changed_bytes))
        render_ms.append((label, statistics.median(timings)))
    return {
        'evidence_type': 'offline_host_mock_widgets', 'physical_dma_used': False,
        'real_widget_comm_or_browser_used': False, 'simulated_frames': 60,
        'simulated_phase_rate_hz': 20,
        'decode_median_ms': {'baseline': median_ms(lambda: previous.decode_frame(packet)),
                             'optimized': median_ms(lambda: current.decode_frame(packet))},
        'render_preparation_median_ms': dict(render_ms),
        'changed_html_bytes': dict(payloads),
        'limitations': 'Timing depends on this desktop. Payload counts exclude widget protocol headers. '
                       'Optimized render preparation includes its throttled FFT. '
                       'No board FPS or analog accuracy claim follows from these results.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=ROOT/'build/reports/optimization_20261025/software_baseline')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = run(args.baseline)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)
