set root [file normalize [file join [file dirname [info script]] .. ..]]
open_checkpoint [file join $root build work vivado phase_measure phase_measure.runs impl_1 system_wrapper_routed.dcp]
set cells [get_cells -hier -filter {NAME =~ *dac_control_0*da_data*reg*}]
if {[llength $cells] != 20} {error "Expected 20 DAC output registers, found [llength $cells]"}
foreach cell $cells {
    set loc [get_property LOC $cell]
    if {![string match OLOGIC* $loc]} {error "$cell is not in OLOGIC: $loc"}
}
puts "DAC_IOB_PASS: 20 output registers placed in OLOGIC"
close_design
