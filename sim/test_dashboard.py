"""Host-side dashboard state tests without requiring a Jupyter installation."""
from pathlib import Path
import sys
import types
import unittest
import asyncio
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/ps'))


class Layout:
    def __init__(self, **kwargs):
        self.display = ''
        self.__dict__.update(kwargs)


class Widget:
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)
        self.value = args[0] if args else kwargs.get('value', '')
        self.description = kwargs.get('description', '')
        self.disabled = kwargs.get('disabled', False)
        self.layout = kwargs.get('layout', Layout())

    def observe(self, *args, **kwargs):
        pass

    def on_click(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


widgets = types.ModuleType('ipywidgets')
for name in ('ToggleButtons', 'FloatSlider', 'Checkbox', 'Button', 'HTML', 'Output', 'VBox', 'HBox'):
    setattr(widgets, name, Widget)
widgets.Layout = Layout
sys.modules.setdefault('ipywidgets', widgets)

matplotlib = types.ModuleType('matplotlib')
pyplot = types.ModuleType('matplotlib.pyplot')
matplotlib.pyplot = pyplot
sys.modules.setdefault('matplotlib', matplotlib)
sys.modules.setdefault('matplotlib.pyplot', pyplot)

ipython = types.ModuleType('IPython')
ipython_display = types.ModuleType('IPython.display')
ipython_display.clear_output = lambda **kwargs: None
ipython_display.display = lambda *args, **kwargs: None
sys.modules.setdefault('IPython', ipython)
sys.modules.setdefault('IPython.display', ipython_display)

from dashboard import Dashboard, MODE_DAC, MODE_EXTERNAL, CALIBRATION_FRAMES
from phase_measure import decode_frame, phase_to_direction_deg
from test_driver import packet


class Instrument:
    def __init__(self):
        self.phase_zero_deg = 0.0
        self.dac_setting = dict(phase_deg=90.0, gain=0.5, enabled=False)

    def set_dac(self, phase_deg=90.0, gain=0.5, enabled=True):
        self.dac_setting = dict(phase_deg=phase_deg, gain=gain, enabled=enabled)
        return self.dac_setting.copy()

    def stop_dac(self):
        return self.set_dac(**{**self.dac_setting, 'enabled': False})

    def calibrate_zero(self, frames=32):
        assert frames == CALIBRATION_FRAMES
        self.phase_zero_deg = 2.5
        return self.phase_zero_deg


def frame(phase=45, sequence=1, otr=False):
    result = decode_frame(packet(phase=phase, otr=otr))
    result['sequence'] = sequence
    result['calibrated_phase_deg'] = result['phase_deg']
    return result


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now


class DashboardTests(unittest.TestCase):
    def test_calibration_failure_exports_diagnostics_and_keeps_measurement_gated(self):
        instrument = Instrument()
        instrument.last_calibration_report = {'status': 'failed'}
        instrument.save_calibration_diagnostics = lambda path: path
        ui = Dashboard(instrument)
        def fail(**kwargs):
            instrument.last_calibration_report = {'status': 'failed', 'attempted': 9}
            raise RuntimeError('I/Q最大差=2')
        with patch.object(instrument, 'calibrate_zero', side_effect=fail):
            with patch.object(instrument, 'save_calibration_diagnostics') as save:
                ui._calibrate(None)
        self.assertTrue(ui.start.disabled)
        self.assertIsNone(ui.calibrations[MODE_DAC])
        self.assertEqual(instrument.phase_zero_deg, 0)
        self.assertEqual(save.call_count, 1)
        self.assertIn('diagnostics/calibration_failure_', save.call_args[0][0])
        self.assertIn('I/Q最大差=2', ui.message.value)

    def test_dac_setup_failure_never_exports_stale_calibration(self):
        instrument = Instrument()
        instrument.last_calibration_report = {'status': 'success'}
        instrument.save_calibration_diagnostics = lambda path: path
        ui = Dashboard(instrument)
        with patch.object(instrument, 'set_dac', side_effect=RuntimeError('DAC update failed')):
            with patch.object(instrument, 'save_calibration_diagnostics') as save:
                ui._calibrate(None)
        save.assert_not_called()
        self.assertTrue(ui.start.disabled)
        self.assertIn('DAC update failed', ui.message.value)

    def test_each_mode_requires_and_retains_its_own_calibration(self):
        instrument = Instrument()
        ui = Dashboard(instrument)
        self.assertEqual(ui.mode, MODE_DAC)
        self.assertTrue(ui.start.disabled)
        self.assertEqual((ui.phase.min, ui.phase.max), (-180, 180))
        self.assertFalse(hasattr(ui, 'rate'))

        ui._calibrate(None)
        self.assertFalse(ui.start.disabled)
        self.assertEqual(ui.calibrations[MODE_DAC]['offset'], 2.5)
        self.assertEqual(instrument.dac_setting['phase_deg'], 0.0)
        self.assertTrue(instrument.dac_setting['enabled'])

        ui._mode_changed({'new': MODE_EXTERNAL})
        self.assertEqual(ui.mode, MODE_EXTERNAL)
        self.assertTrue(ui.start.disabled)
        self.assertFalse(instrument.dac_setting['enabled'])
        self.assertEqual(instrument.phase_zero_deg, 0.0)
        self.assertIn('等待有效信号', ui.model_out.value)
        self.assertNotIn('等效来波', ui.model_out.value)
        self.assertEqual(ui.spectrum_out.value, '')

        ui._calibrate(None)
        self.assertFalse(ui.start.disabled)
        self.assertEqual(ui.calibrations[MODE_EXTERNAL]['offset'], 2.5)

        ui._mode_changed({'new': MODE_DAC})
        self.assertFalse(ui.start.disabled)
        self.assertEqual(instrument.phase_zero_deg, 2.5)

    def test_lightweight_svg_charts_and_out_of_range_state(self):
        ui = Dashboard(Instrument())
        freq = np.linspace(0, 25_000_000, 2049)
        dbfs = np.full((2049, 2), -100.0)
        dbfs[1024] = (-5.0, -6.0)
        html = ui._charts_html(freq, dbfs, [12_500_000, 12_500_000], 45.0, 30.0, True, 7)
        self.assertEqual(html.count('<svg'), 3)
        self.assertIn('远场模拟测向场景', html)
        self.assertIn('θ = +30.00°', html)
        self.assertIn('相位超出测向范围', ui._far_field_svg(120.0, float('nan'), False))
        self.assertLess(html.index('pm-model'), html.index('pm-spectrum'))

    def test_spectrum_reduction_preserves_single_bin_peak(self):
        values = np.full(2049, -100.0)
        values[1024] = -4.25
        reduced = Dashboard._max_pool(values, bins=320)
        self.assertEqual(len(reduced), 320)
        self.assertAlmostEqual(float(np.max(reduced)), -4.25)

    def test_vectorized_pool_matches_every_original_interval_for_both_channels(self):
        values = np.random.default_rng(17).normal(size=(2049, 2))
        values[1024] = [123.0, 124.0]
        for bins in (1, 256, 320, 2049):
            actual = Dashboard._max_pool(values, bins)
            edges = np.linspace(0, len(values), bins + 1).astype(int)
            expected = np.array([values[start:stop].max(axis=0) for start, stop in zip(edges[:-1], edges[1:])])
            np.testing.assert_array_equal(actual, expected)
        with self.assertRaises(ValueError): Dashboard._max_pool(values, 0)

    def test_tick_profiles_capture_fft_and_complete_render(self):
        ui = Dashboard(Instrument())
        clock = Clock()
        result = frame()
        calls = []
        def capture(**kwargs):
            calls.append(kwargs)
            clock.now += 0.010
            return result
        def update(value, now):
            clock.now += 0.020
            ui._spectrum_snapshot = {'freq': None, 'dbfs': None}
        def render(*args): clock.now += 0.040
        ui.instrument.capture = capture
        with patch('dashboard.time.monotonic', clock), patch.object(ui, '_update_spectrum', update), patch.object(ui, '_render', render):
            total = ui._tick()
        self.assertAlmostEqual(total, 0.070)
        self.assertAlmostEqual(ui.last_timings_ms['capture'], 10)
        self.assertAlmostEqual(ui.last_timings_ms['fft'], 20)
        self.assertAlmostEqual(ui.last_timings_ms['render'], 40)
        self.assertAlmostEqual(ui.last_timings_ms['total'], 70)
        self.assertEqual(calls, [{'reuse_buffer': True}])

    def test_fps_uses_completion_window_and_resets_after_restart(self):
        ui = Dashboard(Instrument())
        result = frame()
        ui.instrument.capture = lambda **kwargs: result
        def spectrum_snapshot(value, now):
            ui._spectrum_snapshot = {'freq': None, 'dbfs': None}
        with patch.object(ui, '_update_spectrum', spectrum_snapshot), patch.object(ui, '_render'):
            for stamp in (0.0, 0.08, 0.10):
                with patch('dashboard.time.monotonic', return_value=stamp):
                    ui._tick()
        self.assertAlmostEqual(ui.actual_fps,20.0)
        ui._reset_stream_state()
        self.assertEqual(len(ui._frame_completion_times),0)
        self.assertTrue(np.isnan(ui.actual_fps))

    def test_deadline_sleep_uses_full_tick_and_does_not_queue_catchup(self):
        for duration, expected in ((0.080, 0.0), (0.020, 0.030)):
            ui = Dashboard(Instrument())
            sleeps = []
            async def sleep(delay):
                sleeps.append(delay)
                raise asyncio.CancelledError
            with patch.object(ui, '_tick', return_value=duration), patch('dashboard.asyncio.sleep', sleep):
                asyncio.run(ui._loop())
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], expected)

    def test_spectrum_is_throttled_and_keeps_its_source_frame(self):
        ui = Dashboard(Instrument())
        for moment, sequence in ((0.0, 11), (0.05, 12), (0.10, 13)):
            result = frame(sequence=sequence)
            with patch('dashboard.time.monotonic', return_value=moment):
                ui._update_spectrum(result, moment)
                snapshot = ui._spectrum_snapshot
                ui._render(result, snapshot['freq'], snapshot['dbfs'], result['phase_deg'], 30, 0.01)
        self.assertEqual(ui._spectrum_snapshot['sequence'], 11)
        first_spectrum = ui.spectrum_out.value
        result = frame(sequence=14)
        ui._update_spectrum(result, 0.21)
        with patch('dashboard.time.monotonic', return_value=0.21):
            snapshot = ui._spectrum_snapshot
            ui._render(result, snapshot['freq'], snapshot['dbfs'], result['phase_deg'], 30, 0.01)
        self.assertEqual(ui._spectrum_snapshot['sequence'], 14)
        self.assertEqual(first_spectrum, ui.spectrum_out.value)
        self.assertNotIn('源帧', ui.spectrum_out.value)

    def test_circular_smoothing_raw_error_and_invalid_frame_remain_honest(self):
        ui = Dashboard(Instrument())
        self.assertAlmostEqual(ui._display_phase(179.9, True, 0), 179.9)
        shown = ui._display_phase(-179.9, True, 0.05)
        self.assertGreater(abs(shown), 179.8)
        self.assertTrue(np.isnan(ui._display_phase(0, False, 0.1)))
        self.assertEqual(ui._display_phase(45, True, 0.15), 45)
        ui.instrument.dac_setting['phase_deg'] = -45
        result = frame(-45.6)
        ui._update_spectrum(result, 0.2)
        ui._phase_vector = complex(np.cos(np.deg2rad(-45.0)), np.sin(np.deg2rad(-45.0)))
        ui._phase_time = 0.19
        with patch('dashboard.time.monotonic', return_value=0.2):
            snapshot = ui._spectrum_snapshot
            ui._render(result, snapshot['freq'], snapshot['dbfs'], -45.6, phase_to_direction_deg(-45.6), 0.01)
        self.assertAlmostEqual(ui.last_raw_phase, -45.6)
        self.assertGreater(ui.last_display_phase, -45.6)
        self.assertIn('相位误差 <b>-0.60°', ui.metric_cards.value)
        self.assertNotIn('原始校正相位', ui.metric_cards.value)
        result = frame(otr=True)
        with patch('dashboard.time.monotonic', return_value=0.25):
            ui._render(result, snapshot['freq'], snapshot['dbfs'], float('nan'), float('nan'), 0.01)
        self.assertFalse(ui.last_signal_valid)
        self.assertIsNone(ui._phase_vector)
        self.assertIn('信号无效', ui.metric_cards.value)
        self.assertIn('输入超量程', ui.message.value)

    def test_valid_phase_outside_bearing_range_stays_visible(self):
        ui = Dashboard(Instrument())
        result = frame(120)
        ui._update_spectrum(result, 0)
        snapshot = ui._spectrum_snapshot
        with patch('dashboard.time.monotonic', return_value=0):
            ui._render(result, snapshot['freq'], snapshot['dbfs'], result['phase_deg'], float('nan'), 0.01)
        self.assertTrue(ui.last_signal_valid)
        self.assertFalse(ui.last_direction_valid)
        self.assertIn('超出测向范围', ui.metric_cards.value)
        self.assertIn(f'{result["phase_deg"]:+.3f}', ui.metric_cards.value)
        self.assertNotIn('等效来波', ui.model_out.value)

    def test_presentation_prioritizes_measurements_and_hides_debug_text(self):
        ui = Dashboard(Instrument())
        result = frame()
        ui._update_spectrum(result, 0)
        snapshot = ui._spectrum_snapshot
        with patch('dashboard.time.monotonic', return_value=0):
            ui._render(result, snapshot['freq'], snapshot['dbfs'], 45, 30, .01)
        content = ''.join(getattr(ui, name).value for name in (
            'header', 'guide', 'calibration_status', 'metric_cards', 'message',
            'spectrum_out', 'history_out', 'model_out'))
        for debug in ('FPS', 'CORDIC', 'OTR=', 'codes', '源帧', '采集/解码', 'pm.recover'):
            self.assertNotIn(debug, content)
        self.assertIn('font-size:64px', ui.header.value)
        self.assertIn('实测相位差', ui.metric_cards.value)
        self.assertIn('测向角', ui.metric_cards.value)
        self.assertEqual(ui.guide.value, '')

    def test_scene_direction_uses_bearing_angle_and_invalid_has_no_source(self):
        # Radius 220, theta=30deg, center=(500,300): (610,109.47).
        svg = Dashboard._far_field_svg(45, 30, True)
        self.assertIn('cx="610.0" cy="109.5"', svg)
        self.assertIn('等待有效信号', Dashboard._far_field_svg(float('nan'), float('nan'), False))
        self.assertNotIn('等效来波', Dashboard._far_field_svg(float('nan'), float('nan'), False))

    def test_weak_input_keeps_warning_without_a_fabricated_direction(self):
        ui = Dashboard(Instrument())
        result = frame()
        result['amplitude'][0] = .2
        result['valid'] = False
        ui._update_spectrum(result, 0)
        snapshot = ui._spectrum_snapshot
        with patch('dashboard.time.monotonic', return_value=0):
            ui._render(result, snapshot['freq'], snapshot['dbfs'], 45, 30, .01)
        self.assertFalse(ui.last_direction_valid)
        self.assertIn('信号偏弱', ui.message.value)
        self.assertNotIn('等效来波', ui.model_out.value)

    def test_gain_change_invalidates_only_dac_calibration(self):
        ui = Dashboard(Instrument())
        ui._calibrate(None)
        ui.calibrations[MODE_EXTERNAL] = {'offset': 1.0, 'time': 'test'}
        ui.gain.value = 0.75
        ui._apply_dac(None)
        self.assertIsNone(ui.calibrations[MODE_DAC])
        self.assertEqual(ui.calibrations[MODE_EXTERNAL]['offset'], 1.0)
        self.assertTrue(ui.start.disabled)
        self.assertEqual(ui.instrument.phase_zero_deg, 0)

    def test_capture_fault_invalidates_zero_before_recovery(self):
        ui = Dashboard(Instrument())
        ui._calibrate(None)
        with patch.object(ui, '_tick', side_effect=RuntimeError('DMA fault')):
            asyncio.run(ui._loop())
        self.assertIsNone(ui.calibrations[MODE_DAC])
        self.assertTrue(ui.start.disabled)
        self.assertIn('重新校正', ui.message.value)


if __name__ == '__main__':
    unittest.main(verbosity=2)
