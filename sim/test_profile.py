"""Synthetic tests for profiling statistics/evidence; no PYNQ hardware is used."""
import csv
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('profile_pynq', ROOT / 'src/ps/profile_pynq.py')
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class Instrument:
    def __init__(self):
        self.calls = []
        self.packet = np.arange(32, dtype=np.uint32)

    def capture(self, timeout, reuse_buffer):
        self.calls.append((timeout, reuse_buffer))
        index = len(self.calls)
        phase = -45.6 + index * 0.01
        return {'sequence': index, 'flags': 1, 'valid': index != 2,
                'pipeline_consistent': True, 'overrange': index == 2, 'test_mode': False,
                'raw_phase_deg': phase + 1, 'calibrated_phase_deg': phase,
                'software_phase_deg': phase + 1, 'amplitude': [113.3, 100.5],
                'timings_ms': {stage: float(index) for stage in profile.TIMING_STAGES},
                'words': self.packet, 'samples': np.zeros((16, 2), dtype=np.int32)}


class ProfileTests(unittest.TestCase):
    def test_circular_wrap_statistics_and_undefined_mean(self):
        summary = profile.circular_summary([179.9, -179.9, float('nan')])
        self.assertAlmostEqual(abs(summary['mean_deg']), 180)
        self.assertAlmostEqual(summary['std_deg'], 0.1)
        self.assertAlmostEqual(summary['peak_to_peak_deg'], 0.2)
        self.assertEqual(summary['nonfinite_count'], 1)
        self.assertIsNone(profile.circular_summary([0, 180])['mean_deg'])
        self.assertIsNone(profile.circular_summary([])['std_deg'])

    def test_capture_preserves_raw_and_excludes_invalid_from_statistics(self):
        instrument = Instrument()
        rows, words = profile.collect_frames(instrument, 3, reference_deg=-45)
        self.assertEqual(instrument.calls, [(2.0, True)] * 3)
        self.assertEqual(rows[0]['capture_decode_ms'], 1)
        self.assertAlmostEqual(rows[0]['reference_error_deg'], -0.59)
        self.assertTrue(np.isnan(rows[1]['reference_error_deg']))
        self.assertEqual(rows[0]['pl_software_error_deg'], 0)
        instrument.packet[:] = 0
        self.assertEqual(int(words[0][-1]), 31)
        summary = profile.summarize_rows(rows)
        self.assertEqual(summary['valid_consistent_frames'], 2)
        self.assertEqual(summary['invalid_or_inconsistent_frames'], 1)
        self.assertAlmostEqual(summary['reference_error_deg']['mean_deg'], -0.58)
        self.assertAlmostEqual(summary['reference_error_deg']['std_deg'], 0.01)

    def test_partial_evidence_survives_interruption(self):
        class Interrupted(Instrument):
            def capture(self, **kwargs):
                if self.calls:
                    raise KeyboardInterrupt()
                return super().capture(**kwargs)
        rows, words = [], []
        with self.assertRaises(KeyboardInterrupt):
            profile.collect_frames(Interrupted(), 3, rows=rows, words=words)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(words), 1)

    def test_csv_npz_correspond_and_output_never_overwrites(self):
        rows, words = profile.collect_frames(Instrument(), 3, reference_deg=-45)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'synthetic_run'
            profile.write_run(output, rows, words, {'evidence_type': 'synthetic_test_fixture'})
            with np.load(output / 'raw_frames.npz', allow_pickle=False) as data:
                self.assertEqual(data['words'].shape, (3, 32))
                self.assertEqual(list(data['sequence']), [1, 2, 3])
            with (output / 'frames.csv').open(newline='', encoding='utf-8') as stream:
                saved = list(csv.DictReader(stream))
            self.assertEqual(len(saved), 3)
            self.assertEqual(saved[1]['overrange'], 'True')
            self.assertEqual(json.loads((output / 'metadata.json').read_text())['evidence_type'], 'synthetic_test_fixture')
            with self.assertRaises(FileExistsError):
                profile.write_run(output, rows, words, {})

    def test_manifest_is_read_only_and_detects_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            bit = directory / 'demo.bit'
            hwh = directory / 'demo.hwh'
            bit.write_bytes(b'test fixture bit')
            hwh.write_text('<test_fixture/>')
            manifest = directory / 'manifest.json'
            manifest.write_text(json.dumps({p.name: {'bytes': p.stat().st_size,
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in [bit, hwh]}))
            before = manifest.read_bytes()
            profile.verify_manifest(manifest, bit)
            bit.write_bytes(b'replaced')
            with self.assertRaises(ValueError): profile.verify_manifest(manifest, bit)
            self.assertEqual(manifest.read_bytes(), before)

    def test_help_does_not_load_hardware(self):
        result = subprocess.run([sys.executable, str(ROOT / 'src/ps/profile_pynq.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--dac-phase', result.stdout)

    def test_cli_external_capture_stays_dac_off_and_closes_owner(self):
        owners = []
        class ExternalInstrument(Instrument):
            def __init__(self, bit, encoding):
                super().__init__()
                self.phase_zero_deg = 0
                self.closed = False
                owners.append(self)
            def set_dac(self, *args, **kwargs):
                raise AssertionError('External mode must not enable board DAC')
            def close(self): self.closed = True
        modules = {'phase_measure': types.SimpleNamespace(PhaseMeasure=ExternalInstrument, spectrum=None),
                   'pynq': types.SimpleNamespace(__version__='synthetic_test_fixture')}
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, modules), redirect_stdout(io.StringIO()):
            result = profile.main(['--frames', '2', '--reference-deg', '0', '--output', str(Path(temp) / 'external')])
            self.assertEqual(result, 0)
            self.assertTrue(owners[0].closed)
            metadata = json.loads((Path(temp) / 'external/metadata.json').read_text())
            self.assertEqual(metadata['mode'], 'external_dac_off')
            self.assertEqual(metadata['status'], 'complete')

    def test_gain_without_explicit_dac_phase_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as context:
            profile.main(['--gain', '0.75'])
        self.assertEqual(context.exception.code, 2)

    def test_flat_deployment_resolves_driver_overlay_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            script = app / 'profile_pynq.py'
            shutil.copy2(ROOT / 'src/ps/profile_pynq.py', script)
            (app / 'phase_measure.py').write_text('# layout fixture; never imported\n')
            module = runpy.run_path(str(script))
            args = module['parser']().parse_args([])
            self.assertEqual(module['APP'], app)
            self.assertEqual(Path(args.bit), app / 'overlay/far_field_radio_df.bit')
            self.assertEqual(Path(args.manifest), app / 'manifest.json')


if __name__ == '__main__':
    unittest.main(verbosity=2)
