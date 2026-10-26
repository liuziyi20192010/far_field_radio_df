set root [file normalize [file join [file dirname [info script]] .. ..]]
open_project [file join $root build work vivado phase_measure phase_measure.xpr]
foreach source [get_files -all] {
    set path [get_property NAME $source]
    if {![file exists $path]} {error "Project source missing after relocation: $path"}
}
puts "RELOCATED_PROJECT_PASS"
close_project
