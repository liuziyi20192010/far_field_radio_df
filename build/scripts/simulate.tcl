set root [file normalize [file join [file dirname [info script]] .. ..]]
create_project -force phase_rtl_sim [file join $root build work logs rtl_sim] -part xc7z020clg400-2
add_files [glob [file join $root src rtl *.v]]
add_files [glob [file join $root src rtl *.mem]]
add_files -fileset sim_1 [glob [file join $root sim *.sv]]
set_property top tb_phase_measure [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation
run all
close_sim
set_property top tb_dac_control [get_filesets sim_1]
launch_simulation
run all
close_sim
set_property top tb_cordic_phase [get_filesets sim_1]
launch_simulation
run all
close_sim
close_project
