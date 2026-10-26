# Vivado 2020.2; self-contained, never modifies either source project.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set proj [file join $root build work vivado phase_measure phase_measure.xpr]
if {[file exists $proj]} {error "Project already exists: $proj. Open it or run build.tcl; do not overwrite it."}
create_project phase_measure [file dirname $proj] -part xc7z020clg400-2
set_property target_language Verilog [current_project]
add_files -norecurse [glob [file join $root src rtl *.v]]
add_files -norecurse [glob [file join $root src rtl *.mem]]
add_files -fileset constrs_1 -norecurse [file join $root src constraints phase_measure.xdc]
update_compile_order -fileset sources_1
# PS DDR/MIO/HP0 configuration and DMA interrupt topology are inherited verbatim.
# Delay validation until all new ports are wired.
set fh [open [file join $root build scripts base_system_bd.tcl] r]
set base [read $fh]; close $fh
set base [string map [list {  validate_bd_design} {  # validated by create_project.tcl} \
    {CONFIG.C_GPIO_WIDTH {2}} {CONFIG.C_GPIO_WIDTH {3}} \
    {CONFIG.c_sg_length_width {14}} {CONFIG.c_sg_length_width {20}}] $base]
eval $base
set_property CONFIG.NUM_MI 4 [get_bd_cells ps7_0_axi_periph]

create_bd_port -dir I -from 9 -to 0 ad_data_2
create_bd_port -dir I ad_otr_2
create_bd_port -dir O ad_clk_2
create_bd_port -dir O ad_oe_2
connect_bd_net [get_bd_ports ad_data_2] [get_bd_pins adc_capture_0/ad_data_2]
connect_bd_net [get_bd_ports ad_otr_2] [get_bd_pins adc_capture_0/ad_otr_2]
connect_bd_net [get_bd_pins adc_clk_wiz/clk_out1] [get_bd_ports ad_clk_2]
connect_bd_net [get_bd_pins const_zero/dout] [get_bd_ports ad_oe_2]

# One input buffer/MMCM serves all three clocks; two IBUFs on sys_clk cannot place.
set_property -dict [list CONFIG.CLKOUT3_USED true CONFIG.CLKOUT3_REQUESTED_OUT_FREQ 125] [get_bd_cells adc_clk_wiz]
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_dac
create_bd_cell -type module -reference dac_control dac_control_0
create_bd_cell -type module -reference dac_ack_sync dac_ack_sync_0
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 dac_gpio
set_property -dict [list CONFIG.C_IS_DUAL 1 CONFIG.C_GPIO_WIDTH 21 CONFIG.C_ALL_OUTPUTS 1 \
    CONFIG.C_GPIO2_WIDTH 1 CONFIG.C_ALL_INPUTS_2 1 CONFIG.C_DOUT_DEFAULT 0x00000000] [get_bd_cells dac_gpio]
connect_bd_net [get_bd_pins reset_and/Res] [get_bd_pins rst_dac/ext_reset_in]
connect_bd_net [get_bd_pins adc_clk_wiz/locked] [get_bd_pins rst_dac/dcm_locked]
connect_bd_net [get_bd_pins adc_clk_wiz/clk_out3] [get_bd_pins rst_dac/slowest_sync_clk] [get_bd_pins dac_control_0/clk]
connect_bd_net [get_bd_pins rst_dac/peripheral_aresetn] [get_bd_pins dac_control_0/resetn]
connect_bd_net [get_bd_pins dac_gpio/gpio_io_o] [get_bd_pins dac_control_0/config_async]
connect_bd_net [get_bd_pins dac_control_0/ack] [get_bd_pins dac_ack_sync_0/ack_async]
connect_bd_net [get_bd_pins dac_ack_sync_0/ack_sync] [get_bd_pins dac_gpio/gpio2_io_i]
connect_bd_intf_net [get_bd_intf_pins ps7_0_axi_periph/M03_AXI] [get_bd_intf_pins dac_gpio/S_AXI]
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins dac_gpio/s_axi_aclk] \
    [get_bd_pins ps7_0_axi_periph/M03_ACLK] [get_bd_pins dac_ack_sync_0/clk]
connect_bd_net [get_bd_pins rst_ps7_0_100M/peripheral_aresetn] [get_bd_pins dac_gpio/s_axi_aresetn] \
    [get_bd_pins ps7_0_axi_periph/M03_ARESETN] [get_bd_pins dac_ack_sync_0/resetn]
foreach ch {1 2} {
    create_bd_port -dir O -from 9 -to 0 da_data_$ch
    create_bd_port -dir O da_clk_$ch
    connect_bd_net [get_bd_ports da_data_$ch] [get_bd_pins dac_control_0/da_data_$ch]
    connect_bd_net [get_bd_ports da_clk_$ch] [get_bd_pins dac_control_0/da_clk_$ch]
}
assign_bd_address -offset 0x41210000 -range 0x00010000 \
    -target_address_space [get_bd_addr_spaces processing_system7_0/Data] [get_bd_addr_segs dac_gpio/S_AXI/Reg]
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
add_files -norecurse [make_wrapper -files [get_files system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
write_bd_tcl -force [file join $root build scripts phase_measure_bd.tcl]
puts "PHASE_PROJECT_PASS"
close_project
