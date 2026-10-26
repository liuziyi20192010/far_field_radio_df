set root [file normalize [file join [file dirname [info script]] .. ..]]
open_project [file join $root build work vivado phase_measure phase_measure.xpr]
open_run impl_1
report_cdc -details -file [file join $root build work logs cdc_details.rpt]
close_project
