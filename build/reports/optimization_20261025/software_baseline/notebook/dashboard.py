"""Calibration-gated real-time Jupyter GUI for the dual-channel phase system."""
import asyncio
import math
import time
from datetime import datetime

import ipywidgets as w
import numpy as np
from IPython.display import display

from phase_measure import (
    CARRIER_HZ,
    SAMPLE_RATE_HZ,
    diagnose_frame,
    phase_measurement_error_deg,
    phase_to_delay_ns,
    phase_to_direction_deg,
    spectrum,
)


MODE_DAC = 'dac'
MODE_EXTERNAL = 'external'
TARGET_FPS = 20.0
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
        self.mode = MODE_DAC
        self.calibrations = {MODE_DAC: None, MODE_EXTERNAL: None}

        self.mode_select = w.ToggleButtons(
            options=[('板载 DAC 双路输入', MODE_DAC), ('外部信号输入', MODE_EXTERNAL)],
            value=MODE_DAC, description='输入模式',
            style={'description_width': '70px'}, layout=w.Layout(width='100%'),
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
        self.apply = w.Button(description='应用 DAC 设置', icon='check', button_style='primary')
        self.off = w.Button(description='关闭 DAC', icon='power-off', button_style='warning')
        self.apply.on_click(self._apply_dac)
        self.off.on_click(self._off)

        self.calibrate = w.Button(
            description='执行零相位自校正', icon='crosshairs', button_style='info',
            layout=w.Layout(width='220px'),
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
        self.out = w.HTML(layout=w.Layout(width='100%'))

        self.dac_panel = w.VBox(
            [
                w.HTML('<div class="pm-section-title">板载 DAC 信号设置</div>'),
                self.phase, self.gain,
                w.HBox([self.enable, self.apply, self.off], layout=w.Layout(grid_gap='10px', flex_flow='row wrap')),
            ],
            layout=w.Layout(border='1px solid #dbe4ee', padding='12px 14px', width='100%'),
        )
        self.controls = w.VBox(
            [
                self.mode_select, self.guide, self.dac_panel,
                w.HBox(
                    [self.calibrate, self.start, self.stop],
                    layout=w.Layout(grid_gap='10px', align_items='center', flex_flow='row wrap'),
                ),
                self.calibration_status, self.message,
            ],
            layout=w.Layout(border='1px solid #dbe4ee', padding='14px 16px', width='100%'),
        )
        self.ui = w.VBox(
            [self.header, self.controls, self.metric_cards, self.dac_metrics, self.out],
            layout=w.Layout(width='100%', max_width='1280px'),
        )
        self._refresh_mode_ui()

    @staticmethod
    def _header_html():
        return """
        <style>
          .pm-shell {font-family: system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
                     background:linear-gradient(120deg,#102a43,#0b7285); color:white;
                     border-radius:12px; padding:18px 22px; margin-bottom:10px;}
          .pm-title {font-size:23px; font-weight:700; letter-spacing:.2px;}
          .pm-subtitle {opacity:.82; margin-top:4px; font-size:13px;}
          .pm-section-title {font-size:14px; font-weight:700; color:#243b53; margin-bottom:8px;}
          .pm-guide {background:#f4f8fb; border-left:4px solid #0b7285; padding:10px 12px;
                     color:#334e68; line-height:1.65; margin:8px 0 12px;}
          .pm-state {display:inline-block; border-radius:999px; padding:3px 9px; margin-right:7px;
                     font-size:12px; font-weight:650;}
          .pm-ok {background:#d3f9d8;color:#087f5b}.pm-warn {background:#fff3bf;color:#a15c00}
          .pm-run {background:#d0ebff;color:#1864ab}.pm-stop {background:#e9ecef;color:#52606d}
          .pm-metrics {display:grid;grid-template-columns:repeat(4,minmax(145px,1fr));gap:10px;margin:10px 0;}
          .pm-card {background:white;border:1px solid #dbe4ee;border-radius:10px;padding:12px 14px;
                    box-shadow:0 2px 8px rgba(16,42,67,.05)}
          .pm-label {font-size:12px;color:#627d98}.pm-value {font-size:24px;font-weight:730;color:#102a43;
                     margin-top:2px}.pm-unit {font-size:12px;color:#829ab1;margin-left:3px}
          .pm-detail {background:#f8fafc;border:1px solid #dbe4ee;border-radius:9px;padding:10px 14px;
                      color:#334e68;margin:0 0 10px;line-height:1.6}
          .pm-error {color:#c92a2a}.pm-muted {color:#627d98}
          .pm-chart-grid {display:grid;grid-template-columns:minmax(420px,1.25fr) minmax(320px,.75fr);
                          grid-template-rows:auto auto;gap:10px;margin-top:10px;}
          .pm-chart {background:#fff;border:1px solid #dbe4ee;border-radius:10px;padding:9px 10px;
                     box-shadow:0 2px 8px rgba(16,42,67,.04);overflow:hidden}
          .pm-spectrum {grid-column:1;grid-row:1}.pm-history {grid-column:1;grid-row:2}
          .pm-model {grid-column:2;grid-row:1 / span 2}
          .pm-chart-title {font-size:13px;font-weight:700;color:#334e68;margin:0 0 4px 4px}
          .pm-chart svg {display:block;width:100%;height:auto}
          @media (max-width:820px){.pm-metrics{grid-template-columns:repeat(2,minmax(130px,1fr))}
            .pm-chart-grid{grid-template-columns:1fr}.pm-spectrum,.pm-history,.pm-model{grid-column:1;grid-row:auto}}
        </style>
        <div class="pm-shell">
          <div class="pm-title">远场模拟无线电实时测向系统</div>
          <div class="pm-subtitle">正点原子领航者 ZYNQ7020 · PYNQ 2.7 · 双路 50 MSPS ADC · 12.5 MHz · 等效阵元间距 6 m</div>
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
        if is_dac:
            self.guide.value = (
                '<div class="pm-guide"><b>校正准备：</b>仪表板会把板载 DAC 自动设为两路同相（0°）并开启输出，'
                '采集 8 帧计算通道与线缆的固定偏差。确认 DAC1→ADC1、DAC2→ADC2 后点击“执行零相位自校正”。'
                'DAC 可设 −180°～+180°；远场方位仅在实测相位 ±90°内有物理解。</div>'
            )
        else:
            self.guide.value = (
                '<div class="pm-guide"><b>校正准备：</b>请将外部双通道信号源设为 12.5 MHz、等幅、相位差 0°，'
                '使用等长同型号 50 Ω 线缆连接 ADC1/ADC2。确认信号稳定后点击“执行零相位自校正”。'
                '切换到本模式时板载 DAC 已关闭。</div>'
            )
        calibration = self.calibrations[self.mode]
        if calibration is None:
            self.calibration_status.value = (
                '<span class="pm-state pm-warn">待校正</span>'
                f'<span class="pm-muted">{MODE_LABELS[self.mode]}尚未建立零相位基准；实时测量已锁定。</span>'
            )
            self.start.disabled = True
        else:
            self.calibration_status.value = (
                '<span class="pm-state pm-ok">已校正</span>'
                f'零点偏差 <b>{calibration["offset"]:+.3f}°</b> · {calibration["time"]}'
            )
            self.start.disabled = False
        self.metric_cards.value = self._metric_html(mode=self.mode)
        self.dac_metrics.value = self._dac_metric_html()
        if not self.message.value:
            self._set_message('请选择输入模式并完成该模式的零相位自校正。')

    def _apply_dac(self, _):
        try:
            setting = self.instrument.set_dac(self.phase.value, self.gain.value, self.enable.value)
            self.phase.value = setting['phase_deg']
            self.gain.value = setting['gain']
            self._set_message(
                f'DAC 设置已应用：CH2−CH1={setting["phase_deg"]:+.3f}°，幅度比例={setting["gain"]:.3f}，'
                f'输出={"开启" if setting["enabled"] else "关闭"}。'
            )
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
        self.calibrate.description = '正在采集 8 帧…'
        self._set_message('正在执行圆均值零相位校正，请保持输入稳定。')
        try:
            if self.mode == MODE_DAC:
                setting = self.instrument.set_dac(phase_deg=0.0, gain=self.gain.value, enabled=True)
                self.phase.value = setting['phase_deg']
                self.gain.value = setting['gain']
                self.enable.value = True
            else:
                self.instrument.stop_dac()
            offset = self.instrument.calibrate_zero(frames=8)
            self.calibrations[self.mode] = {
                'offset': float(offset), 'time': datetime.now().strftime('%H:%M:%S'),
            }
            self.history.clear()
            self.angle_history.clear()
            self._set_message(
                f'{MODE_LABELS[self.mode]}校正完成，固定偏差 {offset:+.3f}° 已作为本模式零点。现在可以开始测量。'
            )
        except Exception as exc:
            self.calibrations[self.mode] = None
            self.instrument.phase_zero_deg = 0.0
            self._set_message(f'自校正失败：{exc}', error=True)
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
            self.task = asyncio.create_task(self._loop())
            self.start.disabled = True
            self.stop.disabled = False
            self.calibrate.disabled = True
            self.mode_select.disabled = True
            self._set_message('<span class="pm-state pm-run">测量中</span>正在连续采集与刷新。', raw=True)

    def _stop(self, _):
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.task = None
        self.stop.disabled = True
        self.calibrate.disabled = False
        self.mode_select.disabled = False
        self.start.disabled = self.calibrations[self.mode] is None
        if self.calibrations[self.mode] is not None:
            self._set_message('<span class="pm-state pm-stop">已停止</span>采集已停止，校正值和 DAC 输出状态保持。', raw=True)

    async def _loop(self):
        try:
            while True:
                started = time.monotonic()
                result = self.instrument.capture()
                freq, dbfs = spectrum(result['samples'])
                phase = float(result['calibrated_phase_deg'])
                angle = phase_to_direction_deg(phase)
                elapsed = time.monotonic() - started
                self._render(result, freq, dbfs, phase, angle, elapsed)
                await asyncio.sleep(max(0.0, 1 / TARGET_FPS - elapsed))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.task = None
            self.stop.disabled = True
            self.start.disabled = self.calibrations[self.mode] is None
            self.calibrate.disabled = False
            self.mode_select.disabled = False
            self._set_message(f'刷新停止：{exc}。DMA 故障后请先运行 pm.recover()。', error=True)

    def _render(self, result, freq, dbfs, phase, angle, elapsed):
        peaks = [float(freq[np.argmax(dbfs[:, channel])]) for channel in (0, 1)]
        peak_hz = sum(peaks) / 2
        bin_hz = SAMPLE_RATE_HZ / len(result['samples'])
        frequency_ok = all(abs(value - CARRIER_HZ) <= 2 * bin_hz for value in peaks)
        amplitude_ratio = result['amplitude'][1] / max(result['amplitude'][0], 1e-12)
        balance_ok = 0.25 <= amplitude_ratio <= 4.0
        phase_range_ok = math.isfinite(angle)
        valid = bool(result['valid']) and math.isfinite(phase) and phase_range_ok and frequency_ok and balance_ok
        if valid:
            self.history.append(phase)
            self.angle_history.append(angle)
            self.history = self.history[-120:]
            self.angle_history = self.angle_history[-120:]
        lock_label = 'LOCK' if valid else ('OUT OF RANGE' if not phase_range_ok else 'INVALID')
        self.metric_cards.value = self._metric_html(
            f'{phase:+.3f}' if valid else '—', f'{angle:+.2f}' if valid else '—',
            f'{peak_hz / 1e6:.4f}', lock_label,
            valid=valid, mode=self.mode,
        )
        if self.mode == MODE_DAC:
            reference = float(self.instrument.dac_setting['phase_deg'])
            delay = phase_to_delay_ns(phase) if valid else float('nan')
            expected_delay = phase_to_delay_ns(reference)
            error = phase_measurement_error_deg(phase, reference) if valid else float('nan')
            self.dac_metrics.value = self._dac_metric_html(delay, expected_delay, error, reference)

        now = time.monotonic()
        actual_fps = float('nan') if self._last_frame_time is None else 1.0 / max(now - self._last_frame_time, 1e-9)
        fps_text = '—' if not math.isfinite(actual_fps) else f'{actual_fps:.1f}'
        self._last_frame_time = now
        self.out.value = self._charts_html(freq, dbfs, peaks, phase, angle, valid, result['sequence'])

        difference = phase_measurement_error_deg(result['raw_phase_deg'], result['software_phase_deg'])
        diagnostic = diagnose_frame(result)
        if result['valid'] and not phase_range_ok:
            diagnostic = f'|Δφ|={abs(phase):.2f}° 超出 d=λ/4 模型的 ±90° 可解范围，未强行夹成 90°'
        elif result['valid'] and not frequency_ok:
            diagnostic = '主峰偏离 12.5 MHz，方向输出已冻结'
        elif result['valid'] and not balance_ok:
            diagnostic = '双通道幅度比异常，方向输出已冻结'
        lock_text = lock_label
        self._set_message(
            '<span class="pm-state {}">{}</span>'.format('pm-ok' if valid else 'pm-warn', lock_text)
            + f'帧 {result["sequence"]} · CH1/CH2 幅度 {result["amplitude"][0]:.1f}/{result["amplitude"][1]:.1f} codes '
            + f'· 实际 {fps_text} FPS · 采集/计算 {elapsed * 1000:.0f} ms '
            + f'· CORDIC−软件 {difference:+.4f}° · OTR={result["overrange"]} · {diagnostic}', raw=True,
        )

    @staticmethod
    def _polyline(values, x, y, width, height, low, high, max_points=320):
        values = np.asarray(values, dtype=float)
        if not len(values):
            return ''
        count = min(len(values), max_points)
        indices = np.linspace(0, len(values) - 1, count).astype(int)
        selected = np.clip(values[indices], low, high)
        xs = x + np.linspace(0, width, count)
        ys = y + height - (selected - low) / (high - low) * height
        return ' '.join(f'{px:.1f},{py:.1f}' for px, py in zip(xs, ys))

    @staticmethod
    def _max_pool(values, bins=320):
        """Keep narrow FFT peaks while reducing the SVG point count."""
        values = np.asarray(values, dtype=float)
        if len(values) <= bins:
            return values
        edges = np.linspace(0, len(values), bins + 1).astype(int)
        return np.array([
            np.max(values[start:max(start + 1, stop)])
            for start, stop in zip(edges[:-1], edges[1:])
        ])

    @classmethod
    def _spectrum_svg(cls, freq, dbfs, peaks):
        width, height = 700, 255
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
        ch1 = cls._polyline(cls._max_pool(dbfs[:, 0]), x, y, plot_w, plot_h, -100, 5)
        ch2 = cls._polyline(cls._max_pool(dbfs[:, 1]), x, y, plot_w, plot_h, -100, 5)
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
          <g stroke="#dbe4ee" stroke-width="1">{''.join(grid)}</g>
          <g fill="#627d98" font-size="10" font-family="sans-serif">{''.join(labels)}
            <text x="365" y="249" text-anchor="middle">Frequency (MHz)</text>
            <text x="12" y="110" transform="rotate(-90 12 110)" text-anchor="middle">dBFS</text></g>
          <line x1="{ref_x:.1f}" y1="{y}" x2="{ref_x:.1f}" y2="{y + plot_h}" stroke="#495057" stroke-dasharray="5 4"/>
          {peak_lines}<polyline points="{ch1}" fill="none" stroke="#1971c2" stroke-width="1.5"/>
          <polyline points="{ch2}" fill="none" stroke="#f08c00" stroke-width="1.5"/>
          {peak_marks}<g font-size="10" font-family="sans-serif">
          <text x="390" y="25" fill="#1971c2">ADC1 {peaks[0] / 1e6:.4f} MHz / {peak_levels[0]:.1f} dBFS</text>
          <text x="540" y="39" fill="#f08c00">ADC2 {peaks[1] / 1e6:.4f} MHz / {peak_levels[1]:.1f} dBFS</text></g>
        </svg>'''

    def _history_svg(self):
        width, height = 700, 195
        x, y, plot_w, plot_h = 50, 10, 630, 145
        grid = []
        labels = []
        for level in (-90, -45, 0, 45, 90):
            py = y + plot_h - (level + 90) / 180 * plot_h
            grid.append(f'<line x1="{x}" y1="{py:.1f}" x2="{x + plot_w}" y2="{py:.1f}"/>')
            labels.append(f'<text x="43" y="{py + 3:.1f}" text-anchor="end">{level}</text>')
        phase_path = self._polyline(self.history, x, y, plot_w, plot_h, -90, 90, 120)
        angle_path = self._polyline(self.angle_history, x, y, plot_w, plot_h, -90, 90, 120)
        return f'''<svg viewBox="0 0 {width} {height}" role="img" aria-label="相位和方位历史">
          <g stroke="#dbe4ee">{''.join(grid)}</g><g fill="#627d98" font-size="10" font-family="sans-serif">{''.join(labels)}
          <text x="365" y="183" text-anchor="middle">Recent valid frames</text></g>
          <polyline points="{phase_path}" fill="none" stroke="#0b7285" stroke-width="2"/>
          <polyline points="{angle_path}" fill="none" stroke="#845ef7" stroke-width="1.5" opacity=".72"/>
          <g font-size="10" font-family="sans-serif"><text x="545" y="24" fill="#0b7285">Phase</text>
          <text x="600" y="24" fill="#845ef7">Bearing</text></g></svg>'''

    @staticmethod
    def _far_field_svg(phase, angle, valid):
        shown_angle = angle if valid else 0.0
        theta = math.radians(shown_angle)
        color = '#087f5b' if valid and abs(shown_angle) <= 60 else ('#e67700' if valid else '#868e96')
        cx, cy = 215.0, 390.0
        source_x = cx + 150 * math.sin(theta)
        source_y = cy - 300 * math.cos(theta)
        vector = np.array([source_x - cx, source_y - cy])
        vector /= max(float(np.linalg.norm(vector)), 1e-9)
        tangent = np.array([-vector[1], vector[0]])
        fronts = []
        for fraction in (.25, .45, .65):
            center = np.array([cx, cy]) + vector * (300 * fraction)
            a = center - tangent * 110
            b = center + tangent * 110
            fronts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}"/>')
        if valid:
            state = f'θ = {shown_angle:+.2f}°　Δφ = {phase:+.2f}°'
        elif math.isfinite(phase) and abs(phase) > 90:
            state = f'OUT OF RANGE　|Δφ| = {abs(phase):.2f}° > 90°'
        else:
            state = 'SIGNAL INVALID'
        return f'''<svg viewBox="0 0 430 470" role="img" aria-label="动态远场双阵元模型">
          <defs><marker id="pmArrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill="{color}"/></marker></defs>
          <line x1="{cx}" y1="{cy}" x2="{cx}" y2="55" stroke="#adb5bd" stroke-dasharray="5 5"/>
          <text x="222" y="68" fill="#829ab1" font-size="11">array normal</text>
          <g stroke="{color}" stroke-width="1.5" opacity=".24">{''.join(fronts)}</g>
          <line x1="{source_x:.1f}" y1="{source_y:.1f}" x2="{cx:.1f}" y2="{cy - 8:.1f}" stroke="{color}" stroke-width="3" marker-end="url(#pmArrow)"/>
          <circle cx="{source_x:.1f}" cy="{source_y:.1f}" r="8" fill="{color}" stroke="white" stroke-width="2"/>
          <text x="{source_x:.1f}" y="{source_y - 13:.1f}" text-anchor="middle" fill="{color}" font-size="11">far-field source</text>
          <line x1="135" y1="{cy}" x2="295" y2="{cy}" stroke="#334e68" stroke-width="4" stroke-linecap="round"/>
          <circle cx="135" cy="{cy}" r="9" fill="#1971c2" stroke="white" stroke-width="2"/>
          <circle cx="295" cy="{cy}" r="9" fill="#f08c00" stroke="white" stroke-width="2"/>
          <text x="135" y="420" text-anchor="middle" fill="#1971c2" font-size="11">A / ADC1</text>
          <text x="295" y="420" text-anchor="middle" fill="#d9480f" font-size="11">B / ADC2</text>
          <text x="215" y="442" text-anchor="middle" fill="#627d98" font-size="11">d = 6 m = λ/4</text>
          <text x="215" y="463" text-anchor="middle" fill="{color}" font-size="12" font-weight="700">{state}</text>
        </svg>'''

    def _charts_html(self, freq, dbfs, peaks, phase, angle, valid, sequence):
        return f'''<div class="pm-chart-grid">
          <div class="pm-chart pm-spectrum"><div class="pm-chart-title">双路实时频谱 · Hann FFT · 帧 {sequence}</div>
            {self._spectrum_svg(freq, dbfs, peaks)}</div>
          <div class="pm-chart pm-history"><div class="pm-chart-title">校正相位与方位历史</div>
            {self._history_svg()}</div>
          <div class="pm-chart pm-model"><div class="pm-chart-title">等效远场双阵元模型</div>
            {self._far_field_svg(phase, angle, valid)}</div>
        </div>'''

    @staticmethod
    def _metric_html(phase='—', angle='—', peak='—', lock='WAIT', valid=False, mode=MODE_DAC):
        status_color = '#087f5b' if valid else '#a15c00'
        return f"""
        <div class="pm-metrics">
          <div class="pm-card"><div class="pm-label">校正后相位差 CH2−CH1</div><div class="pm-value">{phase}<span class="pm-unit">°</span></div></div>
          <div class="pm-card"><div class="pm-label">远场估计方位角 θ</div><div class="pm-value">{angle}<span class="pm-unit">°</span></div></div>
          <div class="pm-card"><div class="pm-label">双路平均主峰</div><div class="pm-value">{peak}<span class="pm-unit">MHz</span></div></div>
          <div class="pm-card"><div class="pm-label">信号状态 · {MODE_LABELS[mode]}</div><div class="pm-value" style="color:{status_color}">{lock}</div></div>
        </div>
        """

    @staticmethod
    def _dac_metric_html(delay=float('nan'), expected=float('nan'), error=float('nan'), reference=0.0):
        def number(value, digits=3):
            return f'{value:+.{digits}f}' if math.isfinite(value) else '—'
        expected_bearing = phase_to_direction_deg(reference)
        return f"""
        <div class="pm-detail"><b>板载 DAC 闭环测量：</b>
          测得时延 <b>{number(delay)} ns</b>　·　理论时延 {number(expected)} ns　·　
          相位测量误差 <b>{number(error)}°</b>（测量值 − DAC 已应用设定 {reference:+.3f}°）　·　
          DAC 设定对应理论方位 <b>{number(expected_bearing, 2)}°</b>
        </div>
        """

    def _set_message(self, message, error=False, raw=False):
        if raw:
            self.message.value = f'<div class="pm-guide">{message}</div>'
        else:
            css = 'pm-error' if error else ''
            self.message.value = f'<div class="pm-guide {css}">{message}</div>'

    def close(self):
        self._stop(None)
        try:
            self.instrument.stop_dac()
        except Exception:
            pass
