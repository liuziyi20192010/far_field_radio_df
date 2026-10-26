set root [file normalize [file join [file dirname [info script]] .. ..]]
file mkdir [file join $root build work logs]
open_project [file join $root build work vivado phase_measure phase_measure.xpr]
foreach memory [glob [file join $root src rtl *.mem]] {
    if {![llength [get_files -quiet $memory]]} {add_files -norecurse $memory}
}
open_bd_design [get_files system.bd]
foreach name {dac_clk_wiz_locked dac_clk_wiz_clk_out1} {
    set net [get_bd_nets -quiet $name]
    if {[llength $net] && ![llength [get_bd_pins -quiet -of_objects $net]]} {delete_bd_objs $net}
}
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
write_bd_tcl -force [file join $root build scripts phase_measure_bd.tcl]
update_compile_order -fileset sources_1
# A fresh Tcl-created project has no IP synthesis runs until create_ip_run.
# The original script assumed these runs existed from an earlier GUI build.
if {![llength [get_runs -quiet system_adc_capture_0_0_synth_1]]} {
    create_ip_run [get_files system.bd]
}
# Vivado 2020.2 does not always invalidate module-reference OOC checkpoints
# after an RTL-only edit. Explicitly rebuild these modules to prevent stale BITs.
foreach name {system_adc_capture_0_0_synth_1 system_adc_status_sync_0_0_synth_1 system_dac_control_0_0_synth_1 system_dac_ack_sync_0_0_synth_1} {
    reset_run $name
}
reset_run synth_1
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Synthesis failed"}
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {error "Implementation failed"}
open_run impl_1
foreach report {timing_summary drc cdc utilization bus_skew} {
    report_$report -file [file join $root build work logs $report.rpt]
}
report_cdc -details -file [file join $root build work logs cdc_details.rpt]
set fh [open [file join $root build work logs cdc.rpt] r]
set cdc_text [read $fh]; close $fh
if {[regexp -line {^Critical[ \t]} $cdc_text]} {error "Critical CDC paths remain; refusing to export overlay"}
foreach dtype {max min} {
    set p [get_timing_paths -delay_type $dtype -max_paths 1]
    if {[llength $p] && [get_property SLACK $p]<0} {error "Internal $dtype timing failed"}
}
set out [file join $root board app overlay]
file mkdir $out
set bit [file join $root build work vivado phase_measure phase_measure.runs impl_1 system_wrapper.bit]
set hwh [file join $root build work vivado phase_measure phase_measure.gen sources_1 bd system hw_handoff system.hwh]
if {![file exists $bit] || ![file exists $hwh]} {error "BIT/HWH missing"}
file copy -force $bit [file join $out far_field_radio_df.bit]
file copy -force $hwh [file join $out far_field_radio_df.hwh]
puts "PHASE_BUILD_PASS"
close_project
