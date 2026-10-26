# Copied pin mapping from 33_hs_dual_ad/.../hs_dual_ad.xdc, channel 1 only.
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U18} [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN N16} [get_ports sys_rst_n]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V15} [get_ports {ad_data_1[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W15} [get_ports {ad_data_1[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W14} [get_ports {ad_data_1[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y14} [get_ports {ad_data_1[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V12} [get_ports {ad_data_1[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W13} [get_ports {ad_data_1[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U14} [get_ports {ad_data_1[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U15} [get_ports {ad_data_1[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V13} [get_ports {ad_data_1[8]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U13} [get_ports {ad_data_1[9]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y11} [get_ports ad_otr_1]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y13} [get_ports ad_clk_1]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W11} [get_ports ad_oe_1]

# Only the first stages of explicit control/status synchronizers are exempt.
set_false_path -to [get_pins -hier -filter {NAME =~ */ctrl_meta_reg*/D}]
set_false_path -to [get_pins -hier -filter {NAME =~ */status_meta_reg*/D}]
# External reset is asynchronously asserted by the reset IP, synchronously released.
set_false_path -from [get_ports sys_rst_n]

# TODO: add ADC-specific set_input_delay -min/-max for ad_data_1 and ad_otr_1
# after obtaining ADC clock-to-output + PCB delay. Do NOT invent timing numbers.
# The inherited 50 MHz / 180 degree capture phase is a bring-up assumption,
# not a signed-off external ADC timing budget.
