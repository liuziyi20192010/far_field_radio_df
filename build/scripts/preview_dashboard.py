"""Export the production dashboard HTML/SVG with synthetic data for visual QA.

This is a static host preview, not board measurement evidence. Widget controls
are serialized from the real Dashboard widget tree and are not interactive.
"""
import argparse
from html import escape
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sim'))
sys.path.insert(0, str(ROOT / 'src/ps'))
import test_dashboard as fixtures
from dashboard import Dashboard, MODE_DAC, MODE_EXTERNAL
from phase_measure import phase_to_direction_deg


def html_widget(node):
    kind = type(node).__name__
    layout = getattr(node, 'layout', fixtures.Layout())
    if getattr(layout, 'display', '') == 'none':
        return ''
    if kind == 'HTML':
        props = []
        for attribute, css in [('width', 'width'), ('min_width', 'min-width'), ('flex', 'flex')]:
            value = getattr(layout, attribute, '')
            if value:
                props.append(f'{css}:{value}')
        return f'<div style="{";".join(props)}">{node.value}</div>'
    if kind in ('VBox', 'HBox'):
        props = ['display:flex', 'flex-direction:' + ('row' if kind == 'HBox' else 'column')]
        for attribute, css in [('width', 'width'), ('max_width', 'max-width'),
                               ('min_width', 'min-width'), ('border', 'border'),
                               ('padding', 'padding'), ('grid_gap', 'gap'),
                               ('flex', 'flex'), ('flex_flow', 'flex-flow'),
                               ('align_items', 'align-items')]:
            value = getattr(layout, attribute, '')
            if value:
                props.append(f'{css}:{value}')
        return f'<div style="{";".join(props)}">' + ''.join(map(html_widget, node.value)) + '</div>'
    description = escape(node.description)
    if kind == 'FloatSlider':
        return (f'<label class="qa-slider"><span>{description}</span>'
                f'<input type="range" min="{node.min}" max="{node.max}" value="{node.value}" disabled>'
                f'<b>{node.value:.2f}</b></label>')
    if kind == 'Checkbox':
        return f'<label class="qa-check"><input type="checkbox" {"checked" if node.value else ""} disabled>{description}</label>'
    if kind == 'Button':
        css = 'qa-button qa-' + getattr(node, 'button_style', '')
        return f'<button class="{css}" {"disabled" if node.disabled else ""}>{description}</button>'
    if kind == 'ToggleButtons':
        options = ''.join(f'<button class="qa-button {"qa-primary" if value == node.value else ""}">{escape(label)}</button>'
                          for label, value in node.options)
        return f'<div class="qa-modes"><b>{description}</b>{options}</div>'
    raise TypeError(kind)


def create_preview(output, phase=45, mode=MODE_DAC, state='valid'):
    # Distinct subclasses preserve widget kind for a generic static renderer.
    for name in ('ToggleButtons', 'FloatSlider', 'Checkbox', 'Button', 'HTML', 'VBox', 'HBox'):
        setattr(fixtures.widgets, name, type(name, (fixtures.Widget,), {}))
    instrument = fixtures.Instrument()
    instrument.set_dac(phase, .5, True)
    ui = Dashboard(instrument)
    if mode == MODE_EXTERNAL:
        ui._mode_changed({'new': mode})
    ui.calibrations[mode] = {'offset': 0., 'time': 'synthetic'}
    ui.mode_select.value = mode
    ui._refresh_mode_ui()
    ui.phase.value = phase
    result = fixtures.frame(phase, otr=(state == 'overrange'))
    if state == 'weak':
        result['amplitude'][0] = .2
        result['valid'] = False
    ui._update_spectrum(result, 0.)
    snapshot = ui._spectrum_snapshot
    with patch('dashboard.time.monotonic', return_value=0.):
        ui._render(result, snapshot['freq'], snapshot['dbfs'],
                   result['phase_deg'], phase_to_direction_deg(result['phase_deg']), .01)
    html = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模拟数据界面预览 不代表上板测量结果</title><style>
*{box-sizing:border-box}body{margin:0;padding:22px;background:#edf2f6;color:#102a43;
font-family:system-ui,'Microsoft YaHei',sans-serif}main{max-width:1280px;margin:auto;background:white;padding:20px;border-radius:16px}
.qa-label{max-width:1280px;margin:0 auto 12px;font-size:13px;color:#64748b}
.qa-slider{display:flex;align-items:center;gap:8px;width:98%;margin:7px 0;font-size:14px}
.qa-slider span{min-width:76px}.qa-slider input{flex:1;min-width:20px;width:100%;accent-color:#0b7285}.qa-slider b{min-width:50px;text-align:right}
.qa-modes{display:flex;flex-direction:column;gap:8px;align-items:stretch;margin:0 0 7px}.qa-modes b{font-size:14px;margin-right:10px}
.qa-check{display:flex;gap:5px;align-items:center;font-size:14px;white-space:nowrap}
.qa-button{border:1px solid #c8d4df;border-radius:4px;background:#f3f6f8;color:#243b53;padding:8px 15px;
font-family:inherit;font-size:14px;white-space:nowrap}.qa-primary{background:#1971c2;color:white;border-color:#1971c2}
.qa-info{background:#0b7285;color:white;border-color:#0b7285}.qa-success{background:#087f5b;color:white;border-color:#087f5b}
.qa-warning{background:#fff3bf;color:#925e00}.qa-button:disabled{opacity:.5}
</style></head><body><div class="qa-label">模拟数据界面预览 · 静态控件 · 不代表上板测量结果</div><main>'''
    html += html_widget(ui.ui) + '</main></body></html>'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', type=float, default=45)
    parser.add_argument('--mode', choices=[MODE_DAC, MODE_EXTERNAL], default=MODE_DAC)
    parser.add_argument('--state', choices=['valid', 'weak', 'overrange'], default='valid')
    args = parser.parse_args()
    print(create_preview(args.output, args.phase, args.mode, args.state))
