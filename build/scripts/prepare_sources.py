"""Reproduce pin merge, legacy baseline ROM, and exact-phase Q6 DDS coefficients."""
from pathlib import Path
import math
import re
root = Path(__file__).resolve().parents[2]
coe = (root/'src/reference/rom_1024x10b.coe').read_text()
values = list(map(int, re.findall(r'\d+', coe.split('VECTOR=')[1])))
assert len(values) == 1024 and all(0 <= v <= 1023 for v in values)
(root/'src/rtl/sine_1024.mem').write_text(''.join(f'{v:03x}\n' for v in values))
# 5120=lcm(10,1024): all 10 samples for every 10-bit phase code lie
# exactly on this grid. Signed Q6 retains precision until gain is applied;
# final 10-bit converter rounding takes place in dac_control.v.
# Amplitude 511 leaves both +/- peaks inside the offset-binary range.
coefficients = [round(511 * 64 * math.sin(2 * math.pi * n / 5120)) for n in range(5120)]
assert all(-32768 <= value <= 32767 for value in coefficients)
# Keep the physical ROM a power of two for predictable BRAM inference.
# The extra words are never addressed and do not change the 5120 phase grid.
physical_rom = coefficients + [0] * (8192 - len(coefficients))
(root/'src/rtl/sine_5120_q6.mem').write_text(''.join(f'{value & 0xffff:04x}\n' for value in physical_rom), encoding='ascii')
adc = (root/'src/reference/adc_dma_original.xdc').read_text()
dual = (root/'src/reference/adc_dual_original.xdc').read_bytes().decode('utf-8', errors='replace')
dac = (root/'src/reference/dac_original.xdc').read_bytes().decode('utf-8', errors='replace')
xdc = '\n'.join(line for line in adc.splitlines() if line.startswith(('create_clock', 'set_property')))
xdc += '\n# Channel 2 from the original dual ADC pinout.\n'
xdc += '\n'.join(line for line in dual.splitlines() if line.startswith('set_property') and re.search(r'ad_\w+_2', line))
xdc += '\n# Both DAC channels, exactly the original package pins and I/O standard.\n'
xdc += '\n'.join(line for line in dac.splitlines() if line.startswith('set_property') and 'da_' in line)
xdc += '''
# Only explicit first-stage synchronizers; never exempt the measurement datapath.
set_false_path -to [get_pins -hier -filter {NAME =~ */ctrl_meta_reg*/D}]
set_false_path -to [get_pins -hier -filter {NAME =~ */status_meta_reg*/D}]
set_false_path -to [get_pins -hier -filter {NAME =~ */config_meta_reg*/D}]
set_false_path -to [get_pins -hier -filter {NAME =~ */ack_meta_reg*/D}]
set_false_path -from [get_ports sys_rst_n]
# External ADC input and DAC output delay budgets require the actual converter
# datasheets + PCB/cable timing. Original interfaces had no delay budget.
# Do not interpret passing internal timing as external-interface sign-off.
'''
(root/'src/constraints/phase_measure.xdc').write_text(xdc)
print('Legacy ROM, exact-phase signed Q6 ROM, and merged pin constraints generated')
