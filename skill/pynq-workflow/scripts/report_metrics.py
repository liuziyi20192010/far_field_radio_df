"""Extract recognized Vivado resource/timing tables; never replace unknowns with zero."""
import argparse
import json
from pathlib import Path
import re


def parse(reports):
    reports = Path(reports)
    timing = (reports / 'timing_summary.rpt').read_text(encoding='utf-8', errors='replace')
    util = (reports / 'utilization.rpt').read_text(encoding='utf-8', errors='replace')
    summary = re.search(r'WNS\(ns\).*?\n\s*-+[^\n]*\n\s*([\d.\-]+)\s+([\d.\-]+)\s+\d+\s+\d+\s+'
                        r'([\d.\-]+)\s+([\d.\-]+)', timing)
    if not summary:
        raise ValueError('Unrecognized timing summary format; inspect report manually')
    metrics = dict(zip(['wns_ns', 'tns_ns', 'whs_ns', 'ths_ns'], map(float, summary.groups())))
    for key, names in {'lut': ['Slice LUTs', 'CLB LUTs'], 'ff': ['Slice Registers', 'CLB Registers'],
                       'bram_tiles': ['Block RAM Tile'], 'dsp': ['DSPs']}.items():
        match = next((m for name in names if (m := re.search(r'\|\s*' + re.escape(name) +
                         r'\s*\|\s*([\d.]+)\s*\|', util))), None)
        if not match:
            raise ValueError('Missing resource table: ' + key)
        metrics[key] = float(match.group(1))
    metrics['internal_timing_passed'] = metrics['wns_ns'] >= 0 and metrics['whs_ns'] >= 0
    metrics['external_io_signoff'] = 'not_established_by_this_report'
    metrics['source_reports'] = ['timing_summary.rpt', 'utilization.rpt']
    return metrics


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('reports')
    p.add_argument('--output')
    a = p.parse_args()
    result = parse(a.reports)
    text = json.dumps(result, indent=2)
    if a.output: Path(a.output).write_text(text + '\n', encoding='utf-8')
    print(text)
    raise SystemExit(0 if result['internal_timing_passed'] else 1)
