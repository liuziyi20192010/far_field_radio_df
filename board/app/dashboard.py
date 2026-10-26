"""Calibration-gated real-time Jupyter GUI for the dual-channel phase system."""
import asyncio
import math
import time
from datetime import datetime
from functools import lru_cache
from collections import deque
from html import escape

import ipywidgets as w
import numpy as np
from IPython.display import display

from phase_measure import (
    CARRIER_HZ,
    SAMPLE_RATE_HZ,
    phase_measurement_error_deg,
    phase_to_delay_ns,
    phase_to_direction_deg,
    spectrum,
)


MODE_DAC = 'dac'
MODE_EXTERNAL = 'external'
TARGET_FPS = 20.0
SPECTRUM_FPS = 5.0
CHART_FPS = 10.0
STATUS_FPS = 2.0
CALIBRATION_FRAMES = 32
SMOOTHING_TIME_CONSTANT_S = 0.15
MODE_LABELS = {
    MODE_DAC: '板载 DAC 双路输入',
    MODE_EXTERNAL: '外部双通道信号输入',
}


class Dashboard:
    """Two-mode dashboard with independent zero calibration for each input path."""

    def __init__(self, instrument):
        self.instrument = instrument
        self.task = None
        self.history = []
        self.angle_history = []
        self._last_frame_time = None
        self.actual_fps = float('nan')
        self.last_timings_ms = {}
        self._reset_stream_state()
        self.mode = MODE_DAC
        self.calibrations = {MODE_DAC: None, MODE_EXTERNAL: None}

        self.mode_select = w.ToggleButtons(
            options=[('板载 DAC 双路输入', MODE_DAC), ('外部信号输入', MODE_EXTERNAL)],
            value=MODE_DAC, description='输入模式',
            style={'description_width': 'initial', 'button_width': '240px'},
            layout=w.Layout(width='100%', flex_flow='column', align_items='stretch'),
        )
        self.mode_select.observe(self._mode_changed, names='value')
        self.phase = w.FloatSlider(
            value=0, min=-180, max=180, step=360 / 1024,
            description='设定相位差', readout_format='.2f', continuous_update=False,
            style={'description_width': '80px'}, layout=w.Layout(width='98%'),
        )
        self.gain = w.FloatSlider(
            value=0.5, min=0.05, max=1, step=1 / 256,
            description='输出幅度', readout_format='.3f', continuous_update=False,
            style={'description_width': '80px'}, layout=w.Layout(width='98%'),
        )
        self.enable = w.Checkbox(value=True, description='DAC 输出使能', indent=False)
        self.smoothing = w.Checkbox(value=True, description='平滑显示', indent=False)
        self.apply = w.Button(description='应用 DAC 设置', icon='check', button_style='primary')
        self.off = w.Button(description='关闭 DAC', icon='power-off', button_style='warning')
        self.apply.on_click(self._apply_dac)
        self.off.on_click(self._off)

        self.calibrate = w.Button(
            description='零相位校准', icon='crosshairs', button_style='info',
            layout=w.Layout(width='160px'),
        )
        self.calibrate.on_click(self._calibrate)
        self.start = w.Button(
            description='开始实时测量', icon='play', button_style='success', disabled=True,
            layout=w.Layout(width='180px'),
        )
        self.stop = w.Button(description='停止', icon='stop', disabled=True, layout=w.Layout(width='100px'))
        self.start.on_click(self._start)
        self.stop.on_click(self._stop)
        self.header = w.HTML(self._header_html())
        self.guide = w.HTML()
        self.calibration_status = w.HTML()
        self.metric_cards = w.HTML(self._metric_html())
        self.dac_metrics = w.HTML()
        self.message = w.HTML()
        self.spectrum_out = w.HTML(layout=w.Layout(width='100%'))
        self.history_out = w.HTML(layout=w.Layout(width='100%'))
        self.model_out = w.HTML(layout=w.Layout(width='100%'))
        self.out = w.HBox([self.history_out, self.spectrum_out],
                         layout=w.Layout(width='100%', flex_flow='row wrap', grid_gap='12px'))
        self.history_out.layout = w.Layout(width='49%', min_width='280px', flex='1 1 280px')
        self.spectrum_out.layout = w.Layout(width='49%', min_width='280px', flex='1 1 280px')

        self.dac_panel = w.VBox(
            [
                self.phase, self.gain,
                self.enable,
                w.HBox([self.apply, self.off], layout=w.Layout(grid_gap='8px', flex_flow='row wrap')),
            ],
            layout=w.Layout(width='100%', padding='4px 0'),
        )
        self.controls = w.VBox(
            [
                self.mode_select, self.dac_panel,
                w.HBox(
                    [self.calibrate, self.start, self.stop, self.smoothing],
                    layout=w.Layout(grid_gap='10px', align_items='center', flex_flow='row wrap'),
                ),
                self.calibration_status, self.message,
            ],
            layout=w.Layout(border='1px solid #dbe4ee', padding='14px 16px',
                            width='300px', min_width='280px', flex='0 1 300px'),
        )
        self.primary = w.VBox([self.metric_cards, self.model_out],
                              layout=w.Layout(min_width='min(100%, 500px)', flex='1 1 500px'))
        self.main = w.HBox([self.controls, self.primary],
                          layout=w.Layout(width='100%', flex_flow='row wrap',
                                          align_items='flex-start', grid_gap='14px'))
        self.ui = w.VBox(
            [self.header, self.main, self.out],
            layout=w.Layout(width='100%', max_width='1280px'),
        )
        self._refresh_mode_ui()

    @staticmethod
    def _header_html():
        return """
        <style>
          .pm-shell {font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
                     background:#102a43; color:white; border-radius:14px;
                     padding:18px 24px; margin-bottom:10px;}
          .pm-title {font-size:28px; font-weight:750; letter-spacing:.3px;}
          .pm-subtitle {opacity:.75; margin-top:5px; font-size:14px;}
          .pm-section-title {font-size:16px; font-weight:700; color:#243b53; margin-bottom:8px;}
          .pm-guide {color:#334e68; line-height:1.5; margin:4px 0; font-size:14px;}
          .pm-state {display:inline-block; border-radius:999px; padding:3px 9px; margin-right:7px;
                     font-size:14px; font-weight:650;}
          .pm-ok {background:#d3f9d8;color:#087f5b}.pm-warn {background:#fff3bf;color:#a15c00}
          .pm-run {background:#d0ebff;color:#1864ab}.pm-stop {background:#e9ecef;color:#52606d}
          .pm-metrics {display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:12px;margin:12px 0 6px;}
          .pm-card {background:#f3f8fb;border:1px solid #dbe4ee;border-radius:14px;padding:16px 24px;}
          .pm-card-bearing {background:#eef9f5;border-color:#c7e8db}
          .pm-label {font-size:18px;font-weight:650;color:#486581}
          .pm-value {font-size:64px;line-height:1.12;font-weight:760;color:#102a43;
                     font-variant-numeric:tabular-nums;margin-top:7px;letter-spacing:-1px}
          .pm-card-bearing .pm-value {color:#087f5b}
          .pm-unit {font-size:32px;margin-left:5px;letter-spacing:0}
          .pm-summary {display:flex;align-items:center;gap:14px;flex-wrap:wrap;color:#627d98;
                       padding:6px 4px 10px;font-size:14px}
          .pm-detail {color:#486581;margin:0 4px 10px;line-height:1.5;font-size:14px}
          .pm-error {color:#c92a2a}.pm-muted {color:#627d98}
          .pm-chart-grid {display:grid;grid-template-columns:1fr 1fr;gap:12px;}
          .pm-chart {background:#fff;border:1px solid #dbe4ee;border-radius:14px;padding:10px 14px;
                     margin-bottom:12px;overflow:hidden}
          .pm-model {grid-column:1 / span 2;background:#f8fbfd}
          .pm-chart-title {font-size:16px;font-weight:700;color:#334e68;margin:2px 0 5px 4px}
          .pm-secondary .pm-chart-title {font-size:13px;color:#627d98}
          .pm-secondary svg {max-height:145px}
          .pm-chart svg {display:block;width:100%;height:auto}
          @media (max-width:620px){.pm-title{font-size:23px}.pm-value{font-size:48px}
            .pm-label{font-size:16px}.pm-card{padding:14px}.pm-metrics{grid-template-columns:1fr}
            .pm-chart-grid{grid-template-columns:1fr}.pm-model{grid-column:1}}
        </style>
        <div class="pm-shell">
          <div class="pm-title">远场模拟无线电实时测向系统</div>
          <div class="pm-subtitle">双通道相位测量 · 等效远场测向</div>
        </div>
        """

    def show(self):
        display(self.ui)

    def _mode_changed(self, change):
        if change['new'] == self.mode:
            return
        self._stop(None)
        self.mode = change['new']
        self.history.clear()
        self.angle_history.clear()
        self._reset_stream_state()
        calibration = self.calibrations[self.mode]
        self.instrument.phase_zero_deg = 0.0 if calibration is None else calibration['offset']
        if self.mode == MODE_EXTERNAL:
            try:
                self.instrument.stop_dac()
                self.enable.value = False
            except Exception as exc:
                self._set_message(f'切换模式时关闭 DAC 失败：{exc}', error=True)
        self._refresh_mode_ui()

    def _refresh_mode_ui(self):
        is_dac = self.mode == MODE_DAC
        self.dac_panel.layout.display = '' if is_dac else 'none'
        self.dac_metrics.layout.display = '' if is_dac else 'none'
        self.guide.value = ''
        calibration = self.calibrations[self.mode]
        if calibration is None:
            self.calibration_status.value = (
                '<span class="pm-state pm-warn">待校准</span>'
                '<span class="pm-muted">请在两路同相输入下完成零相位校准。</span>'
            )
            self.start.disabled = True
        else:
            self.calibration_status.value = (
                '<span class="pm-state pm-ok">已校准</span>'
            )
            self.start.disabled = False
        self.metric_cards.value = self._metric_html(mode=self.mode)
        self.dac_metrics.value = ''  # DAC details travel in the single fast metrics update.
        self.model_out.value = self._model_html(float('nan'), float('nan'), False)
        self.spectrum_out.value = ''
        self.history_out.value = ''

    def _apply_dac(self, _):
        try:
            previous_gain = self.instrument.dac_setting['gain']
            setting = self.instrument.set_dac(self.phase.value, self.gain.value, self.enable.value)
            self.phase.value = setting['phase_deg']
            self.gain.value = setting['gain']
            self._reset_stream_state()
            if abs(setting['gain'] - previous_gain) > 1e-12 and self.calibrations[MODE_DAC] is not None:
                self._stop(None)
                self.calibrations[MODE_DAC] = None
                self.instrument.phase_zero_deg = 0.0
                self._refresh_mode_ui()
                self._set_message('输出幅度改变，请重新执行本模式零相位校正。')
                return
            self._set_message('DAC 设置已应用。' if setting['enabled'] else 'DAC 输出已关闭。')
        except Exception as exc:
            self._set_message(f'DAC 设置失败：{exc}', error=True)

    def _off(self, _):
        self.enable.value = False
        self._apply_dac(None)

    def _calibrate(self, _):
        self._stop(None)
        self.calibrate.disabled = True
        self.start.disabled = True
        old_description = self.calibrate.description
        self.calibrate.description = '正在校准…'
        self._set_message('正在校准，请保持输入稳定。')
        previous_report = getattr(self.instrument, 'last_calibration_report', None)
        try:
            if self.mode == MODE_DAC:
                setting = self.instrument.set_dac(phase_deg=0.0, gain=self.gain.value, enabled=True)
                self.phase.value = setting['phase_deg']
                self.gain.value = setting['gain']
                self.enable.value = True
            else:
                self.instrument.stop_dac()
            offset = self.instrument.calibrate_zero(frames=CALIBRATION_FRAMES)
            self.calibrations[self.mode] = {
                'offset': float(offset), 'time': datetime.now().strftime('%H:%M:%S'),
                'stats': getattr(self.instrument, 'calibration_stats', None),
            }
            self.history.clear()
            self.angle_history.clear()
            self._reset_stream_state()
            self._set_message('校准完成，可以开始测量。')
        except Exception as exc:
            self.calibrations[self.mode] = None
            self.instrument.phase_zero_deg = 0.0
            detail = f'自校正失败：{exc}'
            save = getattr(self.instrument, 'save_calibration_diagnostics', None)
            report = getattr(self.instrument, 'last_calibration_report', None)
            if save is not None and report is not None and report is not previous_report:
                path = f'diagnostics/calibration_failure_{time.time_ns()}.npz'
                try:
                    save(path)
                    # Keep the diagnostic evidence on disk without adding a debug path to the panel.
                except Exception as save_exc:
                    detail += f'。诊断文件保存失败：{save_exc}'
            self._set_message(detail, error=True)
        finally:
            self.calibrate.disabled = False
            self.calibrate.description = old_description
            self._refresh_mode_ui()

    def _start(self, _):
        calibration = self.calibrations[self.mode]
        if calibration is None:
            self._set_message('请先完成当前输入模式的零相位自校正。', error=True)
            return
        if self.task is None or self.task.done():
            self.instrument.phase_zero_deg = calibration['offset']
            self._reset_stream_state()
            self.task = asyncio.create_task(self._loop())
            self.start.disabled = True
            self.stop.disabled = False
            self.calibrate.disabled = True
            self.mode_select.disabled = True
            self._set_message('<span class="pm-state pm-run">测量中</span>', raw=True)

    def _stop(self, _):
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.task = None
        self.stop.disabled = True
        self.calibrate.disabled = False
        self.mode_select.disabled = False
        self.start.disabled = self.calibrations[self.mode] is None
        if self.calibrations[self.mode] is not None:
            self._set_message('<span class="pm-state pm-stop">已停止</span>', raw=True)

    def _reset_stream_state(self):
        self._spectrum_snapshot = None
        self._spectrum_pending = False
        self._last_chart_time = float('-inf')
        self._last_status_time = float('-inf')
        self._last_status_state = None
        self._phase_vector = None
        self._phase_time = None
        self._last_frame_time = None
        self.actual_fps = float('nan')
        self.spectrum_fps = float('nan')
        self.last_raw_phase = float('nan')
        self.last_display_phase = float('nan')
        self.last_signal_valid = False
        self.last_direction_valid = False
        self.last_timings_ms = {}
        self._frame_completion_times = deque(maxlen=21)

    def _update_spectrum(self, result, now):
        """A spectrum keeps its own source frame/time; it is not a newer phase frame."""
        previous = self._spectrum_snapshot
        if previous is not None and now - previous['time'] + 1e-9 < 1.0 / SPECTRUM_FPS:
            return
        freq, dbfs = spectrum(result['samples'])
        peaks = [float(freq[np.argmax(dbfs[:, channel])]) for channel in (0, 1)]
        bin_hz = SAMPLE_RATE_HZ / len(result['samples'])
        self._spectrum_snapshot = {
            'freq': freq, 'dbfs': dbfs, 'peaks': peaks,
            'frequency_ok': all(abs(value - CARRIER_HZ) <= 2 * bin_hz for value in peaks),
            'sequence': result['sequence'], 'time': now,
            'clock': datetime.now().strftime('%H:%M:%S.%f')[:-3],
        }
        if previous is not None:
            self.spectrum_fps = 1.0 / max(now - previous['time'], 1e-9)
        self._spectrum_pending = True

    def _display_phase(self, phase, valid, now):
        """Smooth only the displayed phase; raw phase and error remain unchanged."""
        if not valid or not math.isfinite(phase):
            self._phase_vector = None
            self._phase_time = None
            return float('nan')
        vector = complex(math.cos(math.radians(phase)), math.sin(math.radians(phase)))
        previous = self._phase_vector
        previous_angle = math.degrees(math.atan2(previous.imag, previous.real)) if previous is not None else phase
        # Deliberate input changes track immediately instead of dragging old values.
        if (not self.smoothing.value or previous is None or
                abs(phase_measurement_error_deg(phase, previous_angle)) > 3.0):
            self._phase_vector = vector
        else:
            dt = max(0.0, now - self._phase_time)
            alpha = 1.0 - math.exp(-dt / SMOOTHING_TIME_CONSTANT_S)
            self._phase_vector = (1.0 - alpha) * previous + alpha * vector
        self._phase_time = now
        return math.degrees(math.atan2(self._phase_vector.imag, self._phase_vector.real))

    def _tick(self):
        """One complete work cycle, including widget serialization/enqueue work."""
        started = time.monotonic()
        result = self.instrument.capture(reuse_buffer=True)
        captured = time.monotonic()
        self._update_spectrum(result, captured)
        computed = time.monotonic()
        snapshot = self._spectrum_snapshot
        phase = float(result['calibrated_phase_deg'])
        self._render(result, snapshot['freq'], snapshot['dbfs'], phase,
                     phase_to_direction_deg(phase), computed - started)
        completed = time.monotonic()
        self._frame_completion_times.append(completed)
        if len(self._frame_completion_times) > 1:
            self.actual_fps = ((len(self._frame_completion_times) - 1) /
                               max(completed - self._frame_completion_times[0], 1e-9))
        self._last_frame_time = completed
        self.last_timings_ms = {
            'capture': 1000 * (captured - started),
            'fft': 1000 * (computed - captured),
            'render': 1000 * (completed - computed),
            'total': 1000 * (completed - started),
            'driver': result.get('timings_ms', {}),
        }
        return completed - started

    async def _loop(self):
        try:
            while True:
                elapsed = self._tick()
                # No catch-up queue; a late frame is followed by the latest capture.
                await asyncio.sleep(max(0.0, 1 / TARGET_FPS - elapsed))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.task = None
            self.calibrations[self.mode] = None
            self.instrument.phase_zero_deg = 0.0
            self._reset_stream_state()
            self.stop.disabled = True
            self._refresh_mode_ui()
            self.start.disabled = True
            self.calibrate.disabled = False
            self.mode_select.disabled = False
            self._set_message(f'测量已停止：{exc}。请恢复设备连接并重新校正。', error=True)

    def _render(self, result, freq, dbfs, phase, angle, elapsed):
        now = time.monotonic()
        snapshot = self._spectrum_snapshot
        peaks = snapshot['peaks']
        peak_hz = sum(peaks) / 2
        frequency_ok = snapshot['frequency_ok'] and now - snapshot['time'] <= 1.0
        amplitude_ratio = result['amplitude'][1] / max(result['amplitude'][0], 1e-12)
        balance_ok = 0.25 <= amplitude_ratio <= 4.0
        signal_valid = (bool(result['valid']) and math.isfinite(phase) and frequency_ok and balance_ok
                        and bool(result.get('pipeline_consistent', True)))
        shown_phase = self._display_phase(phase, signal_valid, now)
        shown_angle = phase_to_direction_deg(shown_phase)
        phase_range_ok = math.isfinite(angle)
        valid = signal_valid and phase_range_ok and math.isfinite(shown_angle)
        self.last_raw_phase, self.last_display_phase = phase, shown_phase
        self.last_signal_valid, self.last_direction_valid = signal_valid, valid
        if signal_valid:
            self.history.append(phase)
            self.angle_history.append(shown_angle)
            self.history = self.history[-120:]
            self.angle_history = self.angle_history[-120:]
        lock_label = '信号正常' if valid else ('超出测向范围' if signal_valid and not phase_range_ok else '信号无效')
        metrics = self._metric_html(
            f'{shown_phase:+.3f}' if signal_valid else '—', f'{shown_angle:+.2f}' if valid else '—',
            f'{peak_hz / 1e6:.4f}', lock_label,
            valid=valid, mode=self.mode, raw_phase=f'{phase:+.3f}' if signal_valid else '—',
        )
        if self.mode == MODE_DAC:
            reference = float(self.instrument.dac_setting['phase_deg'])
            delay = phase_to_delay_ns(phase) if signal_valid else float('nan')
            expected_delay = phase_to_delay_ns(reference)
            error = phase_measurement_error_deg(phase, reference) if signal_valid else float('nan')
            metrics += self._dac_metric_html(delay, expected_delay, error, reference)
        # One fast scalar update; larger graphics are independently throttled.
        self.metric_cards.value = metrics
        if self._spectrum_pending:
            self.spectrum_out.value = (
                '<div class="pm-chart pm-secondary"><div class="pm-chart-title">双路频谱</div>'
                + self._spectrum_svg(freq, dbfs, peaks) + '</div>'
            )
            self._spectrum_pending = False
        state = (lock_label, result['overrange'], self.mode)
        if now - self._last_chart_time >= 1.0 / CHART_FPS or state != self._last_status_state:
            self.history_out.value = ('<div class="pm-chart pm-secondary"><div class="pm-chart-title">相位与测向角变化</div>'
                                      + self._history_svg() + '</div>')
            self.model_out.value = self._model_html(shown_phase if valid else phase, shown_angle, valid)
            self._last_chart_time = now
        if now - self._last_status_time >= 1.0 / STATUS_FPS or state != self._last_status_state:
            diagnostic = ''
            if signal_valid and not phase_range_ok:
                diagnostic = '相位差超出 ±90°，当前阵列模型无法换算测向角。'
            elif result['overrange']:
                diagnostic = '输入超量程，请降低信号幅度。'
            elif np.any(result['amplitude'] < 3.0):
                diagnostic = '输入信号偏弱，请检查信号源和同轴线连接。'
            elif result['valid'] and not frequency_ok:
                diagnostic = '请确认两路输入频率均为 12.5 MHz。'
            elif result['valid'] and not balance_ok:
                diagnostic = '两路输入幅度相差过大，请检查连接。'
            elif not signal_valid:
                diagnostic = '测量数据校验未通过，请检查输入或重新校准。'
            self._set_message(diagnostic, error=not valid) if diagnostic else self._set_message('')
            self._last_status_time, self._last_status_state = now, state

    @staticmethod
    @lru_cache(maxsize=32)
    def _polyline_x(count, x, width):
        return x + np.linspace(0, width, count)

    @staticmethod
    def _polyline(values, x, y, width, height, low, high, max_points=320):
        values = np.asarray(values, dtype=float)
        if not len(values):
            return ''
        count = min(len(values), max_points)
        selected = values if len(values) <= max_points else values[np.linspace(0, len(values) - 1, count).astype(int)]
        selected = np.clip(selected, low, high)
        xs = Dashboard._polyline_x(count, x, width)
        ys = y + height - (selected - low) / (high - low) * height
        return ' '.join(f'{px:.1f},{py:.1f}' for px, py in zip(xs, ys) if math.isfinite(py))

    @staticmethod
    @lru_cache(maxsize=16)
    def _pool_starts(length, bins):
        return np.linspace(0, length, bins + 1).astype(int)[:-1]

    @staticmethod
    def _max_pool(values, bins=320):
        """Keep narrow FFT peaks while reducing the SVG point count."""
        values = np.asarray(values, dtype=float)
        if not isinstance(bins, int) or bins < 1:
            raise ValueError('bins must be a positive integer')
        if len(values) <= bins:
            return values
        return np.maximum.reduceat(values, Dashboard._pool_starts(len(values), bins), axis=0)

    @staticmethod
    @lru_cache(maxsize=1)
    def _spectrum_static():
        x, y, plot_w, plot_h = 50, 12, 630, 200
        grid = []
        labels = []
        for mhz in range(0, 26, 5):
            px = x + mhz / 25 * plot_w
            grid.append(f'<line x1="{px:.1f}" y1="{y}" x2="{px:.1f}" y2="{y + plot_h}"/>')
            labels.append(f'<text x="{px:.1f}" y="232" text-anchor="middle">{mhz}</text>')
        for level in (-100, -75, -50, -25, 0):
            py = y + plot_h - (level + 100) / 105 * plot_h
            grid.append(f'<line x1="{x}" y1="{py:.1f}" x2="{x + plot_w}" y2="{py:.1f}"/>')
            labels.append(f'<text x="43" y="{py + 3:.1f}" text-anchor="end">{level}</text>')
        ref_x = x + (CARRIER_HZ / 1e6) / 25 * plot_w
        return (f'<g stroke="#dbe4ee" stroke-width="1">{"".join(grid)}</g>'
                f'<g fill="#627d98" font-size="10" font-family="sans-serif">{"".join(labels)}'
                '<text x="365" y="249" text-anchor="middle">频率 / MHz</text>'
                '<text x="12" y="110" transform="rotate(-90 12 110)" text-anchor="middle">dBFS</text></g>'
                f'<line x1="{ref_x:.1f}" y1="{y}" x2="{ref_x:.1f}" y2="{y + plot_h}" stroke="#495057" stroke-dasharray="5 4"/>')

    @classmethod
    def _spectrum_svg(cls, freq, dbfs, peaks):
        width, height = 700, 255
        x, y, plot_w, plot_h = 50, 12, 630, 200
        reduced = cls._max_pool(dbfs, bins=256)
        ch1 = cls._polyline(reduced[:, 0], x, y, plot_w, plot_h, -100, 5)
        ch2 = cls._polyline(reduced[:, 1], x, y, plot_w, plot_h, -100, 5)
        peak_levels = [float(np.max(dbfs[:, channel])) for channel in (0, 1)]
        peak_lines = ''.join(
            f'<line x1="{x + (peak / 1e6) / 25 * plot_w:.1f}" y1="{y}" '
            f'x2="{x + (peak / 1e6) / 25 * plot_w:.1f}" y2="{y + plot_h}" stroke="{color}" opacity=".28"/>'
            for peak, color in zip(peaks, ('#1971c2', '#f08c00'))
        )
        peak_marks = ''.join(
            f'<circle cx="{x + (peak / 1e6) / 25 * plot_w:.1f}" '
            f'cy="{y + plot_h - (max(-100, min(5, level)) + 100) / 105 * plot_h:.1f}" '
            f'r="{5 if channel == 0 else 3}" fill="{color if channel else "white"}" '
            f'stroke="{color}" stroke-width="2"/>'
            for channel, (peak, level, color) in enumerate(zip(peaks, peak_levels, ('#1971c2', '#f08c00')))
        )
        return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="双路实时频谱">
          {cls._spectrum_static()}
          {peak_lines}<polyline points="{ch1}" fill="none" stroke="#1971c2" stroke-width="1.5"/>
          <polyline points="{ch2}" fill="none" stroke="#f08c00" stroke-width="1.5"/>
          {peak_marks}<g font-size="10" font-family="sans-serif">
          <text x="390" y="25" fill="#1971c2">ADC1 {peaks[0] / 1e6:.4f} MHz / {peak_levels[0]:.1f} dBFS</text>
          <text x="540" y="39" fill="#f08c00">ADC2 {peaks[1] / 1e6:.4f} MHz / {peak_levels[1]:.1f} dBFS</text></g>
        </svg>'''

    @staticmethod
    @lru_cache(maxsize=1)
    def _history_static():
        x, y, plot_w, plot_h = 50, 10, 630, 145
        grid = []
        labels = []
        for level in (-180, -90, 0, 90, 180):
            py = y + plot_h - (level + 180) / 360 * plot_h
            grid.append(f'<line x1="{x}" y1="{py:.1f}" x2="{x + plot_w}" y2="{py:.1f}"/>')
            labels.append(f'<text x="43" y="{py + 3:.1f}" text-anchor="end">{level}</text>')
        return (f'<g stroke="#dbe4ee">{"".join(grid)}</g><g fill="#627d98" font-size="10">{"".join(labels)}'
                '<text x="365" y="183" text-anchor="middle">最近有效测量</text></g>')

    def _history_svg(self):
        width, height = 700, 195
        x, y, plot_w, plot_h = 50, 10, 630, 145
        phase_path = self._polyline(self.history, x, y, plot_w, plot_h, -180, 180, 120)
        angle_path = self._polyline(self.angle_history, x, y, plot_w, plot_h, -180, 180, 120)
        return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="相位和方位历史">
          {self._history_static()}
          <polyline points="{phase_path}" fill="none" stroke="#0b7285" stroke-width="2"/>
          <polyline points="{angle_path}" fill="none" stroke="#845ef7" stroke-width="1.5" opacity=".72"/>
          <g font-size="11" font-family="sans-serif"><text x="545" y="24" fill="#0b7285">相位</text>
          <text x="600" y="24" fill="#845ef7">测向角</text></g></svg>'''

    @staticmethod
    def _far_field_svg(phase, angle, valid):
        shown_angle = angle if valid else 0.0
        theta = math.radians(shown_angle)
        color = '#087f5b' if valid else '#829ab1'
        cx, cy, radius = 500.0, 300.0, 220.0
        source_x = cx + radius * math.sin(theta)
        source_y = cy - radius * math.cos(theta)
        vx, vy = source_x - cx, source_y - cy
        length = max(math.hypot(vx, vy), 1e-9)
        vx, vy = vx / length, vy / length
        tx, ty = -vy, vx
        fronts = []
        for fraction in (.28, .48, .68):
            center_x, center_y = cx + vx * radius * fraction, cy + vy * radius * fraction
            fronts.append(f'<line x1="{center_x-tx*155:.1f}" y1="{center_y-ty*155:.1f}" '
                          f'x2="{center_x+tx*155:.1f}" y2="{center_y+ty*155:.1f}"/>')
        if valid:
            state = f'θ = {shown_angle:+.2f}°'
        elif math.isfinite(phase) and abs(phase) > 90:
            state = '相位超出测向范围'
        else:
            state = '等待有效信号'
        # A circular radius keeps the drawn direction equal to the measured bearing.
        arrival = f'''
          <g stroke="{color}" stroke-width="2" opacity=".22">{''.join(fronts)}</g>
          <line x1="{source_x:.1f}" y1="{source_y:.1f}" x2="{cx:.1f}" y2="{cy - 8:.1f}"
                stroke="{color}" stroke-width="4" marker-end="url(#pmArrow)"/>
          <circle cx="{source_x:.1f}" cy="{source_y:.1f}" r="12" fill="{color}" stroke="white" stroke-width="3"/>
          <text x="{source_x:.1f}" y="{source_y - 22:.1f}" text-anchor="middle" fill="{color}" font-size="18">等效来波</text>
        ''' if valid else ''
        arc_x, arc_y = cx + 64 * math.sin(theta), cy - 64 * math.cos(theta)
        sweep = 1 if shown_angle >= 0 else 0
        arc = (f'<path d="M {cx} {cy-64} A 64 64 0 0 {sweep} {arc_x:.1f} {arc_y:.1f}" '
               f'fill="none" stroke="{color}" stroke-width="3"/>') if valid and abs(shown_angle) > .1 else ''
        return f'''<svg viewBox="0 0 1000 390" role="img" aria-label="由实测相位换算的等效远场模拟场景">
          <defs><marker id="pmArrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill="{color}"/></marker></defs>
          <path d="M 280 300 A 220 220 0 0 1 720 300" fill="none" stroke="#e0eaf0" stroke-width="2"/>
          <line x1="{cx}" y1="{cy}" x2="{cx}" y2="45" stroke="#bdcedb" stroke-dasharray="6 6"/>
          <text x="516" y="40" fill="#829ab1" font-size="16">正前方 0°</text>
          <text x="256" y="288" fill="#829ab1" font-size="15" text-anchor="end">−90°</text>
          <text x="744" y="288" fill="#829ab1" font-size="15">+90°</text>
          {arrival}{arc}
          <line x1="350" y1="{cy}" x2="650" y2="{cy}" stroke="#334e68" stroke-width="5" stroke-linecap="round"/>
          <circle cx="350" cy="{cy}" r="12" fill="#1971c2" stroke="white" stroke-width="3"/>
          <circle cx="650" cy="{cy}" r="12" fill="#f08c00" stroke="white" stroke-width="3"/>
          <text x="350" y="333" text-anchor="middle" fill="#1971c2" font-size="17">阵元 A / ADC1</text>
          <text x="650" y="333" text-anchor="middle" fill="#d9480f" font-size="17">阵元 B / ADC2</text>
          <text x="500" y="365" text-anchor="middle" fill="#627d98" font-size="17">等效阵元间距 6 m（λ/4）</text>
          <text x="820" y="110" text-anchor="middle" fill="{color}" font-size="23" font-weight="700">{state}</text>
          <text x="820" y="141" text-anchor="middle" fill="#829ab1" font-size="15">相位测量换算方向</text>
        </svg>'''

    @classmethod
    def _model_html(cls, phase, angle, valid):
        return ('<div class="pm-chart pm-model"><div class="pm-chart-title">远场模拟测向场景</div>'
                + cls._far_field_svg(phase, angle, valid) + '</div>')

    def _charts_html(self, freq, dbfs, peaks, phase, angle, valid, sequence):
        return f'''<div class="pm-chart-grid">
          <div class="pm-chart pm-model"><div class="pm-chart-title">远场模拟测向场景</div>
            {self._far_field_svg(phase, angle, valid)}</div>
          <div class="pm-chart pm-history pm-secondary"><div class="pm-chart-title">相位与测向角变化</div>
            {self._history_svg()}</div>
          <div class="pm-chart pm-spectrum pm-secondary"><div class="pm-chart-title">双路频谱</div>
            {self._spectrum_svg(freq, dbfs, peaks)}</div>
        </div>'''

    @staticmethod
    def _metric_html(phase='—', angle='—', peak='—', lock='等待测量', valid=False, mode=MODE_DAC, raw_phase=None):
        status_color = '#087f5b' if valid else '#a15c00'
        return f"""
        <div class="pm-metrics">
          <div class="pm-card"><div class="pm-label">实测相位差 Δφ</div><div class="pm-value">{phase}<span class="pm-unit">°</span></div></div>
          <div class="pm-card pm-card-bearing"><div class="pm-label">测向角 θ</div><div class="pm-value">{angle}<span class="pm-unit">°</span></div></div>
        </div>
        <div class="pm-summary"><span class="pm-state {'pm-ok' if valid else 'pm-warn'}" style="color:{status_color}">{lock}</span>
          <span>{MODE_LABELS[mode]}</span><span>信号频率 {peak} MHz</span></div>
        """

    @staticmethod
    def _dac_metric_html(delay=float('nan'), expected=float('nan'), error=float('nan'), reference=0.0):
        def number(value, digits=3):
            return f'{value:+.{digits}f}' if math.isfinite(value) else '—'
        return f"""
        <div class="pm-detail">DAC 设定 <b>{reference:+.2f}°</b>　·　
          相位误差 <b>{number(error, 2)}°</b>
        </div>
        """

    def _set_message(self, message, error=False, raw=False):
        if not message:
            self.message.value = ''
            return
        if raw:
            self.message.value = f'<div class="pm-guide">{message}</div>'
        else:
            css = 'pm-error' if error else ''
            self.message.value = f'<div class="pm-guide {css}">{escape(str(message))}</div>'

    def close(self):
        self._stop(None)
        try:
            self.instrument.stop_dac()
        except Exception:
            pass
