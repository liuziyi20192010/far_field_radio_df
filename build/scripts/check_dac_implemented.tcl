# Exercise the actual routed DAC primitives: an RTL-only simulation cannot
# detect a ROM address that synthesis incorrectly reduced to a constant.
set root [file normalize [file join [file dirname [info script]] .. ..]]
set work [file join $root build work logs implemented_dac]
file mkdir $work
set checkpoint [file join $root build work vivado phase_measure phase_measure.runs impl_1 system_wrapper_routed.dcp]
open_checkpoint $checkpoint
set dac [get_cells -hier -filter {NAME == system_i/dac_control_0/inst}]
if {[llength $dac] != 1} {error "Expected exactly one implemented DAC cell"}
set netlist [file join $work dac_routed_funcsim.v]
write_verilog -force -mode funcsim -cell $dac $netlist
set fh [open $netlist r];set text [read $fh];close $fh
if {![regexp {module[ \t\r\n]+([A-Za-z_][A-Za-z0-9_]*)[ \t\r\n]*\(} $text match exported_top]} {
    error "Cannot identify exported DAC netlist module"
}
close_design
catch {close_project}
# Keep the testbench independent of Vivado's generated module prefix.
set wrapper [file join $work implemented_dac.v]
set fh [open $wrapper w]
puts $fh "module implemented_dac(input clk,resetn,input \[20:0\] config_async,output ack,output \[9:0\] da_data_1,da_data_2,output da_clk_1,da_clk_2);"
puts $fh "$exported_top impl(.clk(clk),.resetn(resetn),.config_async(config_async),.ack(ack),.da_data_1(da_data_1),.da_data_2(da_data_2),.da_clk_1(da_clk_1),.da_clk_2(da_clk_2));"
puts $fh "endmodule"
close $fh
create_project -force dac_implemented_sim [file join $work project] -part xc7z020clg400-2
add_files [list $netlist $wrapper]
add_files -fileset sim_1 [file join $root sim tb_dac_implemented.sv]
set_property top tb_dac_implemented [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set simlog [file join $work project dac_implemented_sim.sim sim_1 behav xsim simulate.log]
set fh [open $simlog r];set result [read $fh];close $fh
if {![regexp -line {^DAC_IMPLEMENTED_PASS:} $result]} {
    error "Routed DAC simulation did not pass; refusing to approve this hardware export"
}
close_project
puts "DAC_IMPLEMENTED_PASS: routed DAC primitive simulation verified"
