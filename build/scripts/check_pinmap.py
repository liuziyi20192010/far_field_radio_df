"""Verify merged constraints preserve all original pins and I/O standards."""
from pathlib import Path
import re
import json
root=Path(__file__).resolve().parents[2]
def parse(path):
    result={}
    for line in path.read_bytes().decode('utf-8',errors='replace').splitlines():
        if not line.startswith('set_property'):continue
        match=re.search(r'get_ports\s+\{?([\w\[\]]+)',line)
        if not match:continue
        port=match.group(1)
        # Closing get_ports bracket is part of scalar regex matches; vectors end in ]}.
        if '[' not in port:port=port.rstrip(']')
        attrs=result.setdefault(port,{})
        for key in ['PACKAGE_PIN','IOSTANDARD']:
            prop=re.search(key+r'\s+(\w+)',line)
            if prop:
                if key in attrs:assert attrs[key]==prop.group(1)
                attrs[key]=prop.group(1)
    return result
expected={}
for name in ['adc_dma_original.xdc','adc_dual_original.xdc','dac_original.xdc']:
    for port,props in parse(root/'src/reference'/name).items():
        if port in expected:assert expected[port]==props,(port,expected[port],props)
        expected[port]=props
actual=parse(root/'src/constraints/phase_measure.xdc')
assert expected==actual,(expected,actual)
assert len(actual)==50,len(actual)
pins=[props['PACKAGE_PIN'] for props in actual.values()]
assert len(set(pins))==len(pins),'Package pin collision'
assert all(props['IOSTANDARD']=='LVCMOS33' for props in actual.values())
(root/'build/reports/current/pinmap.json').write_text(json.dumps(actual,indent=2))
print('PINMAP_PASS: 50 ports, identical original pins/IOSTANDARD, no collisions')
