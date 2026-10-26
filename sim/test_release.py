"""Software deployment cannot bless changed hardware or build provenance."""
from pathlib import Path
import importlib.util
import json
import tempfile
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_artifacts', ROOT/'build/scripts/check_artifacts.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class SoftwareReleaseTests(unittest.TestCase):
    def test_notebook_run_all_keeps_panel_open_and_rerun_closes_old_objects(self):
        class Instrument:
            def __init__(self, **kwargs): self.closed = False
            def test_link(self): return True
            def close(self): self.closed = True

        class Panel:
            def __init__(self, instrument): self.closed = False
            def show(self): self.visible = True
            def close(self): self.closed = True

        notebook = json.loads((ROOT/'board/app/far_field_radio_df.ipynb').read_text(encoding='utf-8'))
        namespace = {}
        with patch.dict(sys.modules, {
            'phase_measure': types.SimpleNamespace(PhaseMeasure=Instrument),
            'dashboard': types.SimpleNamespace(Dashboard=Panel),
        }):
            def run_all():
                for cell in notebook['cells']:
                    if cell['cell_type'] == 'code':
                        exec(compile(''.join(cell['source']), '<notebook>', 'exec'), namespace)
            run_all()
            first_panel, first_instrument = namespace['ui'], namespace['pm']
            self.assertTrue(first_panel.visible)
            self.assertFalse(first_panel.closed)
            self.assertFalse(first_instrument.closed)
            run_all()
            self.assertTrue(first_panel.closed)
            self.assertTrue(first_instrument.closed)
            self.assertFalse(namespace['ui'].closed)
            self.assertFalse(namespace['pm'].closed)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.app = self.root/'board/app'
        files = {'src/rtl/core.v': b'rtl', 'src/rtl/table.mem': b'rom',
                 'src/constraints/phase_measure.xdc': b'pins',
                 'board/app/overlay/far_field_radio_df.bit': b'bit',
                 'board/app/overlay/far_field_radio_df.hwh': b'hwh'}
        for name, content in files.items():
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.patches = patch.multiple(checks, ROOT=self.root, APP=self.app)
        self.patches.start()
        self.addCleanup(self.patches.stop)
        info = dict(bit_sha256=checks.file_record(self.app/'overlay/far_field_radio_df.bit')['sha256'],
                    hardware_sources={p.relative_to(self.root).as_posix(): checks.file_record(p)['sha256']
                                      for p in checks.hardware_inputs()},
                    metadata_recorded_utc='original-build-time', board_test_status='pending')
        (self.app/'build_info.json').write_text(json.dumps(info), encoding='utf-8')
        manifest = {n: checks.file_record(self.app/n) for n in
                    ('overlay/far_field_radio_df.bit', 'overlay/far_field_radio_df.hwh', 'build_info.json')}
        (self.app/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def test_software_changes_preserve_original_build_info(self):
        original = (self.app/'build_info.json').read_bytes()
        (self.app/'phase_measure.py').write_text('changed software', encoding='utf-8')
        checks.verify_software_hardware()
        self.assertEqual((self.app/'build_info.json').read_bytes(), original)

    def test_changed_exports_and_metadata_are_rejected(self):
        for name in ('overlay/far_field_radio_df.bit', 'overlay/far_field_radio_df.hwh', 'build_info.json'):
            path = self.app/name
            original = path.read_bytes()
            with self.subTest(name=name):
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'unchanged hardware'):
                    checks.verify_software_hardware()
                path.write_bytes(original)

    def test_changed_missing_and_added_hardware_inputs_are_rejected(self):
        path = self.root/'src/rtl/core.v'
        original = path.read_bytes()
        path.write_bytes(b'changed rtl')
        with self.assertRaisesRegex(ValueError, 'Hardware input'):
            checks.verify_software_hardware()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'Hardware input'):
            checks.verify_software_hardware()
        path.write_bytes(original)
        (self.root/'src/rtl/extra.v').write_bytes(b'new rtl')
        with self.assertRaisesRegex(ValueError, 'Hardware input'):
            checks.verify_software_hardware()

    def test_implemented_evidence_requires_actual_pass_for_this_bit(self):
        reports=self.root/'build/reports/current'
        reports.mkdir(parents=True)
        log=reports/'check_dac_implemented.log'
        sha=reports/'implemented_bit.sha256'
        sha.write_text(checks.file_record(self.app/'overlay/far_field_radio_df.bit')['sha256']+'\n')
        log.write_text('# puts "DAC_IMPLEMENTED_PASS: example"\nFatal: CH1 amplitude failure\n')
        with self.assertRaisesRegex(ValueError,'actual implemented'):
            checks.verify_implemented_evidence()
        log.write_text('DAC_IMPLEMENTED_PASS: routed DAC primitive simulation verified\n')
        checks.verify_implemented_evidence()
        sha.write_text('0'*64+'\n')
        with self.assertRaisesRegex(ValueError,'does not describe'):
            checks.verify_implemented_evidence()


if __name__ == '__main__':
    unittest.main(verbosity=2)
