#时序约束
create_clock -period 20.000 -name sys_clk [get_ports sys_clk]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U18} [get_ports sys_clk]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports sys_rst_n]


#------------------------J4˫·AD---------------------------

#ad_data1
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V15} [get_ports {ad_data_1[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W14} [get_ports {ad_data_1[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V12} [get_ports {ad_data_1[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U14} [get_ports {ad_data_1[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V13} [get_ports {ad_data_1[8]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y11} [get_ports ad_otr_1]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y13} [get_ports ad_clk_1]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W15} [get_ports {ad_data_1[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y14} [get_ports {ad_data_1[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W13} [get_ports {ad_data_1[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U15} [get_ports {ad_data_1[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U13} [get_ports {ad_data_1[9]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W11} [get_ports {ad_oe_1}]
#ad_data2
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V11} [get_ports {ad_data_2[0]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W10} [get_ports {ad_data_2[2]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y9} [get_ports {ad_data_2[4]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y7} [get_ports {ad_data_2[6]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W6} [get_ports {ad_data_2[8]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U10} [get_ports ad_otr_2]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN U9} [get_ports ad_clk_2]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V10} [get_ports {ad_data_2[1]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN W9} [get_ports {ad_data_2[3]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y8} [get_ports {ad_data_2[5]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN Y6} [get_ports {ad_data_2[7]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN V6} [get_ports {ad_data_2[9]}]
set_property -dict {IOSTANDARD LVCMOS33 PACKAGE_PIN T9} [get_ports {ad_oe_2}]